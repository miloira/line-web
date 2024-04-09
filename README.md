line-web
===============================================
Line chatbot framework.

Usage
-----

```bash
$ pip install line-web
```


```python
from line import Line
from line.authentications import BusinessAuthentication

bot = Line(
    authentication=BusinessAuthentication("<username>", "<password>"), # Business Account
    bot="<shop>" # Shop Name
)


# event
# chat(message, messageSent, read, typing, typingVanished, noteUpdated, markedAsManualChat, unmarkedAsManualChat, chatRead, assigneeUpdated, tagged, ...)
# botUnreadChatCount(increment, ...)
# botInfo(hasChatRoomChanged, ...)
# ...

@bot.handle()
def on_event(bot, event):
    print(bot, event)


@bot.handle("chat", "message")
def on_message(bot, event):
    pass


bot.run()
```


Meta
----


Distributed under the MIT license. See `LICENSE <https://github.com/miloira/line-web/LICENSE>` for more information.

https://github.com/miloira/line-web