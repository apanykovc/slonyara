# Slonyara

Utilities for structured logging across the project.

## Quick start

1. **Create a virtual environment and install dependencies.**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   make install
   ```

   > [!TIP]
   > Windows environments often lack GNU Make. If `make install` is not
   > available, run the equivalent pip command instead:
   >
   > ```powershell
   > python -m pip install --upgrade pip
   > python -m pip install -r requirements.txt
   > ```

> [!NOTE]
> When using **Python 3.13 on Windows**, installing `pydantic-core`
> requires native compilation. In addition to the Rust toolchain you must
> install the *Microsoft C++ Build Tools* (or the "Desktop development with
> C++" workload in Visual Studio) **including** the MSVC compiler and a
> Windows 10/11 SDK so that `cl.exe`, `link.exe` and the Windows headers
> such as `io.h` are available on the system `PATH`. After installing the
> toolchain, open a new terminal (or run from a "x64 Native Tools Command
> Prompt") before executing `pip install -r requirements.txt`. If setting
> up the build tools is not an option, install Python 3.12 where pre-built
> wheels are still distributed.

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

   If you prefer to run the application directly with Python, use the
   module form of the command:

   ```bash
   python -m main
   ```

   On some platforms (especially Windows), running `python -m main.py`
   raises an error similar to: `ModuleNotFoundError: __path__ attribute
   not found on 'main' while trying to find 'main.py'`. Dropping the
   `.py` suffix is enough to resolve the problem because the `-m` flag
   expects a module name (`main`) rather than a file name (`main.py`).
