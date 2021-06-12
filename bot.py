import asyncio
import datetime
import json
import os
import os.path
import random

import discord


TOKEN_FILE = 'token.conf'
CHANNEL_FILE = 'channel.conf'
ALIASES_FILE = 'aliases.conf'

PREFIX = '.'
COMMANDS = dict()
DESCRIPTIONS = dict()
PARAMETERS = dict()


def command(keys: list[str] = [], params: list[str] = [], usage: str = 'No usage given...'):
    def inner(func):
        for key in keys:
            COMMANDS[key] = func
            PARAMETERS[key] = params
            DESCRIPTIONS[key] = usage

        return func

    return inner


QUOTE_REFRESH_SEC = 300
QUOTE_FILE = 'quotes.180days'
QUOTE_TIMESTAMP_FILE = 'last_reload_time.180days'


def rindex(s, v):
    for i in range(len(s)-len(v), -1, -1):
        if s[i:i+len(v)] == v:
            return i

    return None


def fmt_name(name):
    name = name.lower().strip().split(' ')
    return  ' '.join([f'{v[0].upper()}{v[1:]}' for v in name]).strip()


def fmt_datetime(val):
    return val.strftime('%Y/%m/%d')


def embed(title, description, footer='', colour=discord.Color.gold()):
    embed = discord.Embed(title=title, description=description, colour=colour)
    embed.set_footer(text=footer)
    return embed


def err_embed(title, description, footer='', colour=discord.Color.red()):
    return embed(title, description, footer, colour)


class BotClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.aliases = self.read_aliases()
        self.flat_inv_aliases = {v: k for k, vs in self.aliases.items() for v in vs}
        self.quotes = self.read_quotes()

        self.reload_quote_task = self.loop.create_task(self.bg_reload_quotes())


    def read(self, fpath):
        if not os.path.isfile(fpath):
            return None

        with open(fpath, 'r') as f:
            return f.read()


    def write(self, fpath, value):
        with open(fpath, 'w') as f:
            f.write(value)


    def read_aliases(self):
        aliases = dict()
        for key, value in json.loads(self.read(ALIASES_FILE)).items():
            aliases[key.lower().strip()] = [v.lower().strip() for v in value]

        return aliases


    def write_aliases(self):
        self.write(ALIASES_FILE, json.dumps(self.aliases, indent=4))


    def read_timestamp(self):
        timestamp = self.read(QUOTE_TIMESTAMP_FILE).strip()
        return datetime.datetime.fromisoformat(timestamp) if timestamp is not None else None


    def write_timestamp(self, datetime):
        self.write(QUOTE_TIMESTAMP_FILE, datetime.isoformat())


    def read_quotes(self):
        quotes = self.read(QUOTE_FILE)
        return json.loads(quotes) if quotes is not None else dict()


    def write_quotes(self):
        self.write(QUOTE_FILE, json.dumps(self.quotes, indent=4))


    def add_alias(self, author, alias):
        alias = alias.lower().strip()
        if alias not in self.aliases[author]:
            self.aliases[author].append(alias)
        if alias not in self.flat_inv_aliases:
            self.flat_inv_aliases[alias] = author
        self.write_aliases()


    def del_alias(self, author, alias):
        alias = alias.lower().strip()
        if alias in self.aliases[author]:
            self.aliases[author].remove(alias)
        if alias in self.flat_inv_aliases:
            del self.flat_inv_aliases[alias]
        self.write_aliases()


    def resolve_alias(self, name):
        return self.flat_inv_aliases.get(name.lower().strip(), name.lower().strip())


    def get_quote_split(self, quote):
        separators = ['- ', '– ', '— ']

        for sep in separators:
            if (sep_rindex := rindex(quote, sep)) is not None:
                return sep_rindex

        return None


    async def update_quotes(self, channel, limit=None, after=None):
        async for msg in channel.history(limit=limit, after=after, oldest_first=True):
            try:
                if msg.author.name == self.user.name:
                    continue

                # TODO(mikolaj): find better way of distinguishing quotes from 
                # non-quotes. preferrably have single quote format
                if (quote_split := self.get_quote_split(msg.content)) is None:
                    continue

                author = msg.content[quote_split+1:].lower().strip()

                if ' me ' == f' {author} ':
                    author = msg.author.display_name

                author = fmt_name(self.resolve_alias(author))

                new_quote = [msg.content, fmt_datetime(msg.created_at), msg.jump_url]

                status = self.quotes.get(author, {'total': 0, 'quotes': []})
                status['total'] += 1
                status['quotes'].append(new_quote)
                self.quotes[author] = status

            except Exception as err:
                print(f'"{msg.content}" gives error {err}')
                continue

        self.write_timestamp(datetime.datetime.now())
        self.write_quotes()

        print(f'Updated quote history at {datetime.datetime.now().strftime("%H:%M:%S")}')


    async def bg_reload_quotes(self):
        await self.wait_until_ready()

        channel_id = 0
        try:
            with open(CHANNEL_FILE, 'r') as channel_file:
                channel_id = int(channel_file.read())
        except ValueError:
            print(f'Invalid channel id! Ensure valid ID is in {CHANNEL_FILE}')
            return

        channel = self.get_channel(channel_id)
        if channel is None:
            print(f'Unable to get channel with id: {QUOTE_CHANNEL_ID}!')
            return

        print(f'Fetched source channel: #{channel}')

        try:
            if not os.path.isfile(QUOTE_FILE):
                await self.update_quotes(channel)
            else:
                await self.update_quotes(channel, after=self.read_timestamp())

            while not self.is_closed():
                await asyncio.sleep(QUOTE_REFRESH_SEC)

                await self.update_quotes(channel, after=self.read_timestamp())

        except Exception as err:
            print(err)


    async def bg_reminder(self, author, minutes, message, set_date):
        await asyncio.sleep(minutes * 60)
        await author.send(f'Reminder: {message}')


    async def on_message(self, message):
        import traceback

        if message.author == self.user:
            return

        prefix = message.content[:len(PREFIX)]
        [key, *params] = message.content[len(PREFIX):].strip().split(' ')

        if prefix == PREFIX and 0 < len(key):
            if (handler := COMMANDS.get(key, None)) is not None:
                try:
                    await handler(self, message.author, message.channel, params)
                except Exception as err:
                    traceback.print_exc()
                    error = err_embed('Error', f'{err}\nInvalid usage! Please see .help or .usage')
                    await message.channel.send(embed=error)
            else:
                print(f'Unknown command: "{key}" with parameters {params}')


    @command(keys=['help', 'usage'], params=['[command:str]'], usage='Displays usage information')
    async def usage(self, author, channel, params):
        if len(params) == 0:
            response = 'Available Commands:\n'
            for key in COMMANDS:
                description, parameters = DESCRIPTIONS[key], PARAMETERS[key]

                response += f'  {PREFIX}{key} :\n'
                response += f'    Usage: {PREFIX}{key} {" ".join(parameters)}\n'
                response += f'    Description: {description}\n'

            await channel.send(embed=embed('Usage', response))
        else:
            key = params[0]
            description, parameters = DESCRIPTIONS[key], PARAMETERS[key]

            response =  f'{PREFIX}{key} :\n'
            response += f'  Usage: {PREFIX}{key} {" ".join(parameters)}\n'
            response += f'  Description: {description}'

            await channel.send(embed=embed(f'{key} Usage', response))


    @command(keys=['ping'], params=[], usage='Returns with a pong')
    async def ping(self, author, channel, params):
       await channel.send('pong')


    @command(keys=['alias'], params=['add|del|ls', '<alias:str>'], usage='Add or remove aliases')
    async def alias(self, author, channel, params):
        [verb, *new_alias] = params

        if len(new_alias) == 0:
            raise Exception('No alias given!')

        formatted_id = f'<@{author.id}>'
        author = self.resolve_alias(formatted_id)
        if author == formatted_id:
            pass

        if verb == 'add':
            self.add_alias(author, fmt_name(' '.join(new_alias)))
        elif verb == 'del':
            self.del_alias(author, fmt_name(' '.join(new_alias)))
        elif verb == ls:
            pass
        else:
            raise Exception(f'Unknown verb given: {verb}')

        response = ' '.join(self.aliases[author])

        await channel.send(embed=embed(f'{fmt_name(author)}\'s Aliases', response))


    @command(keys=['tally'], params=[], usage='Quote totals per person')
    async def totals(self, author, channel, params):
        response, total_quotes = 'Quotes per capita:\n', 0

        for author, status in self.quotes.items():
            response += f'\t{author}: {status["total"]} quotes\n'
            total_quotes += status['total']

        response += f'Total Quotes: {total_quotes}'

        await channel.send(embed=embed('Quote Tally', response))


    @command(keys=['random'], params=['[username:str]'], usage='Gets a random quote (optionally from the given user)')
    async def user_quote(self, author, channel, params):
        if len(params) == 0:
            author = random.choice(list(self.quotes.keys()))
        else:
            author = fmt_name(self.resolve_alias(' '.join(params)))
        
        quotes = self.quotes[author]['quotes']
        i = random.randint(0, len(quotes)-1)

        title = f'{author} Quote #{i+1}'
        quote, timestamp, link = quotes[i]
        footer = f'{timestamp}'

        await channel.send(embed=embed(title, quote, footer))


    @command(keys=['history'], params=['<username:str>'], usage='Gets the given users quote history')
    async def user_history(self, author, channel, params):
        author = fmt_name(self.resolve_alias(' '.join(params)))
        quotes = self.quotes[author]['quotes']

        response, page = '', 1
        for i, tup in enumerate(quotes):
            quote, timestamp, link = tup
            formatted_quote = f'#{i+1}: {quote}\n'

            if 2048 <= len(response) + len(formatted_quote):
                await channel.send(embed=embed(f'{author}\'s History ({page})', response))
                response = ''
                page += 1

            response += formatted_quote

        await channel.send(embed=embed(f'{author}\'s History ({page})', response))


    @command(keys=['remind'], params=['<time:int> <scale:hr|min> - <message:str>'], usage='Reminds you about a message after a given time')
    async def set_reminder(self, author, channel, params):
        reminder_mins, reminder_scale = int(params[0]), params[1]

        if reminder_scale != 'hr' and reminder_scale != 'min':
            await channel.send(embed=err_embed('Invalid timescale', 'Please use hr (hours) or min (minutes)'))
            return

        if reminder_scale == 'hr':
            reminder_mins *= 60

        reminder_message = ' '.join(params[2:])
        if '- ' != reminder_message[0:2]:
            await channel.send(embed=err_embed('Invalid separator', 'Please use the \'-\' separator between the expiry and the message'))
            return

        now = datetime.datetime.now()
        reminder_expiry = now + datetime.timedelta(minutes=reminder_mins)

        reminder_task = self.bg_reminder(author, reminder_mins, reminder_message[2:], now.isoformat(' ', 'seconds'))
        self.loop.create_task(reminder_task)

        expiry = reminder_expiry.isoformat(' ', 'seconds')

        await channel.send(embed=embed(f'Set reminder', f'Set the reminder for {expiry} UTC'))


def main():
    token = ''
    with open(TOKEN_FILE, 'r') as token_file:
        token = token_file.read().rstrip()

    bot = BotClient()
    bot.run(token)


if __name__ == '__main__':
    main()

