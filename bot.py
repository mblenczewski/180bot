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
QUOTE_FILE = 'authors.180days'
QUOTE_TIMESTAMP_FILE = 'last_reload_time.180days'


def rindex(s, v):
    for i in range(len(s)-len(v), -1, -1):
        if s[i:i+len(v)] == v:
            return i

    return None


def fmt_name(name):
    name = name.lower().strip()
    return  f'{name[0].upper()}{name[1:]}'


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

        self.quotes = self.read_quotes()

        self.reload_quote_task = self.loop.create_task(self.bg_reload_quotes())


    def read_timestamp(self):
        if not os.path.isfile(QUOTE_TIMESTAMP_FILE):
            return None
        
        with open(QUOTE_TIMESTAMP_FILE, 'r') as f:
            try:
                return datetime.datetime.fromisoformat(f.read().strip())
            except:
                return None


    def write_timestamp(self, datetime):
        with open(QUOTE_TIMESTAMP_FILE, 'w') as f:
            f.write(datetime.isoformat())


    def read_quotes(self):
        if not os.path.isfile(QUOTE_FILE):
            return dict()

        with open(QUOTE_FILE, 'r') as f:
            return json.loads(f.read())


    def write_quotes(self):
        with open(QUOTE_FILE, 'w') as f:
            f.write(json.dumps(self.quotes, indent=4))


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

                if (quote_split := self.get_quote_split(msg.content)) is None:
                    continue

                author = fmt_name(msg.content[quote_split+1:])

                if ' Me ' == f' {author} ':
                    author = fmt_name(msg.author.display_name)

                status = self.quotes.get(author, {'total': 0, 'quotes': []})
                status['total'] += 1
                status['quotes'].append((msg.content, fmt_datetime(msg.created_at), msg.jump_url))
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

                await self.update_quotes(history, channel, after=self.read_timestamp())

        except Exception as err:
            print(err)


    async def bg_reminder(self, author, minutes, message, set_date):
        await asyncio.sleep(minutes * 60)
        await author.send(f'Reminder: {message}')


    async def on_message(self, message):
        if message.author == self.user:
            return

        prefix = message.content[:len(PREFIX)]
        [key, *params] = message.content[len(PREFIX):].strip().split(' ')

        if prefix == PREFIX and 0 < len(key):
            if (handler := COMMANDS.get(key, None)) is not None:
                try:
                    await handler(self, message.author, message.channel, params)
                except Exception as err:
                    print(f'Error duing {command} handler (params: {params}):\n{err}')
                    error = err_embed('Error', f'{err}\nInvalid usage! Please see .help or .usage')
                    await message.channel.send(embed=error)
            else:
                print(f'Unknown command: "{key}" with parameters {params}')


    @command(keys=['help', 'usage'], params=[], usage='Displays usage information')
    async def usage(self, author, channel, params):
        response = 'Available Commands:\n'
        for key in COMMANDS:
            description, parameters = DESCRIPTIONS[key], PARAMETERS[key]

            response += f'  {PREFIX}{key} :\n'
            response += f'    Usage: {PREFIX}{key} {" ".join(parameters)}\n'
            response += f'    Description: {description}\n'

        await channel.send(embed=embed('Usage', response))


    @command(keys=['ping'], params=[], usage='Returns with a pong')
    async def ping(self, author, channel, params):
       await channel.send('pong')


    @command(keys=['tally'], params=[], usage='Quote totals per person')
    async def totals(self, author, channel, params):
        response, total_quotes= 'Quotes per capita:\n', 0

        for author, status in self.quotes.items():
            response += f'\t{author}: {status["total"]} quotes\n'
            total_quotes += status['total']

        response += f'Total Quotes: {total_quotes}'

        await channel.send(embed=embed('Quote Tally', response))


    @command(keys=['random'], params=['<username:str>'], usage='Gets a random quote from the given user')
    async def user_quote(self, author, channel, params):
        if len(params) == 0:
            author = random.choice(list(self.quotes.keys()))
        else:
            author = fmt_name(' '.join(params))
        
        quotes = self.quotes[author]['quotes']
        i = random.randint(0, len(quotes)-1)

        title = f'{author} Quote #{i+1}'
        quote, timestamp, link = quotes[i]
        footer = f'{timestamp}'

        await channel.send(embed=embed(title, quote, footer))


    @command(keys=['history'], params=['<username:str>'], usage='Gets the given users quote history')
    async def user_history(self, author, channel, params):
        author = fmt_name(' '.join(params))
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

