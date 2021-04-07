import asyncio
import datetime
import json
import os
import os.path
import random

import discord


TOKEN_FILE = 'token.conf'
CHANNEL_FILE = 'channel.conf'

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
QUOTE_HISTORY_FILE = 'quotes.180days'
QUOTE_AUTHORS_FILE = 'authors.180days'
QUOTE_REFRESH_FILE = 'last_reload_time.180days'


def rindex(s, v):
    for i in range(len(s)-len(v), -1, -1):
        if s[i:i+len(v)] == v:
            return i

    return None


def format_author_name(name):
    name = name.lower().strip()
    return  f'{name[0].upper()}{name[1:]}'


def embed(title, description, color=discord.Color.gold()):
    return discord.Embed(color=color, title=title, description=description)


def err_embed(title, description, color=discord.Color.red()):
    return embed(title, description, color=color)


class BotClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.authors = self.read_authors()
        self.quotes = self.read_quotes()

        self.reload_quote_task = self.loop.create_task(self.bg_reload_quotes())


    def read_last_reload_time(self):
        if not os.path.isfile(QUOTE_REFRESH_FILE):
            return None
        
        with open(QUOTE_REFRESH_FILE, 'r') as last_reload:
            try:
                return datetime.datetime.fromisoformat(last_reload.read().strip())
            except:
                return None


    def write_last_reload_time(self, datetime):
        with open(QUOTE_REFRESH_FILE, 'w') as last_reload:
            last_reload.write(datetime.isoformat())


    def read_authors(self):
        if not os.path.isfile(QUOTE_AUTHORS_FILE):
            return dict()

        with open(QUOTE_AUTHORS_FILE, 'r') as authors_file:
            return json.loads(authors_file.read())


    def write_authors(self):
        with open(QUOTE_AUTHORS_FILE, 'w') as authors_file:
            authors_file.write(json.dumps(self.authors, indent=4))


    def read_quotes(self):
        if not os.path.isfile(QUOTE_HISTORY_FILE):
            return []

        with open(QUOTE_HISTORY_FILE, 'r') as quote_file:
            return json.loads(quote_file.read())


    def write_quotes(self):
        with open(QUOTE_HISTORY_FILE, 'w') as quote_file:
            quote_file.write(json.dumps(self.quotes, indent=4))


    def get_quote_split(self, quote):
        separators = ['- ', '– ', '— ']

        for sep in separators:
            if (sep_rindex := rindex(quote, sep)) is not None:
                return sep_rindex

        return None


    async def update_quotes(self, history, channel, limit=None, after=None):
        async for msg in channel.history(limit=limit, after=after, oldest_first=True):
            try:
                # ignore bot responses
                if msg.author.name == self.user.name:
                    continue

                # loose message format check
                if (quote_split := self.get_quote_split(msg.content)) is None:
                    continue

                author = format_author_name(msg.content[quote_split+1:])

                if ' Me ' == f' {author} ':
                    author = format_author_name(msg.author.display_name)

                if author not in self.authors:
                    self.authors[author] = {'total': 1, 'quotes': [msg.content]}
                else:
                    self.authors[author]['total'] += 1
                    self.authors[author]['quotes'].append(msg.content)

                self.quotes.append({'author': author, 'quote': msg.content})

            except Exception as err:
                print(f'"{msg.content}" gives error {err}')
                continue

        self.write_last_reload_time(datetime.datetime.now())
        self.write_authors()
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
            # if missing message history file, recreate it
            if not os.path.isfile(QUOTE_HISTORY_FILE):
                with open(QUOTE_HISTORY_FILE, 'w') as history:
                    await self.update_quotes(history, channel)
            else:
                with open(QUOTE_HISTORY_FILE, 'a') as history:
                    await self.update_quotes(history, channel, after=self.read_last_reload_time())

            # update the quote history file every so often
            while not self.is_closed():
                await asyncio.sleep(QUOTE_REFRESH_SEC)

                with open(QUOTE_HISTORY_FILE, 'a') as history:
                    await self.update_quotes(history, channel, after=self.read_last_reload_time())

        except Exception as err:
            print(err)


    async def bg_reminder(self, author, minutes, message, set_date):
        await asyncio.sleep(minutes * 60)
        # await author.send(f'(@{set_date}) Reminder: {message}')
        await author.send(f'Reminder: {message}')


    async def on_message(self, message):
        if message.author == self.user:
            return

        prefix = message.content[:len(PREFIX)]
        parts = message.content[len(PREFIX):].strip().split(' ')

        key, params = parts[0], parts[1:]

        if prefix == PREFIX and 0 < len(key):
            for command, handler in COMMANDS.items():
                if key == command:
                    try:
                        await handler(self, message.author, message.channel, params)
                    except Exception as err:
                        print(f'Error duing {command} handler (params: {params}):\n{err}')
                        error = err_embed('Error', f'{err}\nInvalid usage! Please see .help or .usage')
                        await message.channel.send(embed=error)
                    break
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


    @command(keys=['totals', 'tally'], params=[], usage='Quote totals per person')
    async def totals(self, author, channel, params):
        response, total_quotes= 'Quotes per capita:\n', 0

        for author, info in self.authors.items():
            response += f'\t{author}: {info["total"]} quotes\n'
            total_quotes += info['total']

        response += f'Total Quotes: {total_quotes}'

        await channel.send(embed=embed('Quote Tally', response))


    @command(keys=['quote'], params=[], usage='Gets a random quote')
    async def quote(self, author, channel, params):
        index = random.randint(0, len(self.quotes)-1)

        await channel.send(embed=embed(f'Quote #{index}', self.quotes[index]['quote']))


    @command(keys=['uquote'], params=['<username:str>'], usage='Gets a random quote from the given user')
    async def user_quote(self, author, channel, params):
        author = format_author_name(' '.join(params))
        author_quotes = self.authors[author]['quotes']
        index = random.randint(0, len(author_quotes)-1) 

        await channel.send(embed=embed(f'{author}\'s Quote #{index}', author_quotes[index]))


    @command(keys=['uiquote'], params=['<username:str>', '<index:int>'], usage='')
    async def user_indexed_quote(self, author, channel, params):
        author = format_author_name(' '.join(params[:-1]))
        author_quotes = self.authors[author]['quotes']
        index = int(params[-1])

        await channel.send(embed=embed(f'{author}\'s Quote #{index}', author_quotes[index]))


    @command(keys=['uhistory'], params=['<username:str>'], usage='Gets the given users quote history')
    async def user_history(self, author, channel, params):
        author = format_author_name(' '.join(params))
        author_quotes = self.authors[author]['quotes']

        response, page = '', 1
        for idx, quote in enumerate(author_quotes):
            formatted_quote = f'#{idx}: {quote}\n'

            if 2048 <= len(response) + len(formatted_quote):
                await channel.send(embed=embed(f'{author}\'s History ({page})', response))
                response = ''
                page += 1

            response += formatted_quote

        await channel.send(embed=embed(f'{author}\'s History ({page})', response))


    @command(keys=['iquote'], params=['<index:int>'], usage='Gets the quote with the given index')
    async def index_quote(self, author, channel, params):
        index = int(params[0])

        if index < 0 or len(self.quotes) <= index:
            raise ValueError(f'given index {index} is out of bounds')

        await channel.send(embed=embed(f'Quote #{index}', self.quotes[index]['quote']))


    @command(keys=['test'], params=['<quote:str>'], usage='Checks whether a quote would be accepted')
    async def test_quote(self, author, channel, params):
        quote = ' '.join(params)
        response = ''

        if (quote_split := self.get_quote_split(quote)) is None:
            response = 'Quote not accepted!'
        else:
            response = f'Quote accepted! Author separator index: {quote_split}'

        await channel.send(embed=embed(f'Quote Test: \'{quote}\'', response))


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

