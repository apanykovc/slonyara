# Slonyara

Utilities for structured logging across the project.

## Quick start

1. **Create a virtual environment and install dependencies.**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   make install
   ```

2. **Configure the bot token and runtime options.**

   The project reads configuration values from a `.env` file. An example
   file is already provided with a development token, default storage
   location and reminder timing.

   ```bash
   cat .env
   ```

   Update the values if necessary, or replace them with your production
   credentials before deployment.

3. **Launch the bot.**

   ```bash
   make run
   ```

   The command loads the environment variables from `.env`, initialises
   the meeting storage and reminder services, and starts polling updates
   from Telegram.
