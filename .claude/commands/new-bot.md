Scaffold a new bot named $ARGUMENTS.

1. Create the directory `bots/$ARGUMENTS/`
2. Create `bots/$ARGUMENTS/__init__.py` (empty)
3. Create `bots/$ARGUMENTS/config.yaml` using this template:
   ```yaml
   name: <Title Case of the bot name>
   description: <one line description>
   schedule: "0 9 * * *"   # daily at 09:00 UTC — adjust as needed
   enabled: true
   notify:
     provider: telegram     # or "email"
     on: failure
   ```
4. Create `bots/$ARGUMENTS/bot.py` using this template:
   ```python
   """
   bots/<name>/bot.py
   <one-line description>
   """
   from __future__ import annotations
   from core.logger import get_logger
   import core.config as cfg

   log = get_logger("<name>")


   def run() -> str:
       """Entry point called by the BotRunner scheduler."""
       log.info("--- <Name> run starting ---")
       # TODO: implement
       return "completed successfully"
   ```

After creating the files, print a checklist of what still needs to be done:
- [ ] Fill in the description and adjust the cron schedule in config.yaml
- [ ] Implement `run()` in bot.py
- [ ] Add any required env vars to `.env` and `.env.example`
- [ ] Add new dependencies to `requirements.txt` if needed
