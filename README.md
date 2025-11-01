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
> requires native compilation. Besides the Rust toolchain you must also
> install the Microsoft C++ toolchain, otherwise the build fails with
> errors mentioning missing `link.exe` or headers like `io.h`.
>
> ### Windows toolchain checklist
>
> 1. Install the **Microsoft Visual C++ Build Tools** or the "Desktop
>    development with C++" workload in Visual Studio 2019/2022.
> 2. In the installer make sure the following components are selected:
>    - *MSVC v143 - VS 2022 C++ x64/x86 build tools* (or the latest
>      available MSVC compiler).
>    - *Windows 10 SDK* or *Windows 11 SDK* so the Windows headers (for
>      example `io.h`) are available.
>    - Optionally, *C++ CMake tools for Windows* if you prefer the standalone
>      Build Tools package—it also installs the required `link.exe`.
> 3. Finish the installation and then open a new terminal **or** use the
>    "x64 Native Tools Command Prompt for VS" so the updated `PATH`
>    includes both the MSVC tools and `%USERPROFILE%\.cargo\bin`.
> 4. Activate your virtual environment and run `pip install -r
>    requirements.txt` again.
>
> If setting up the Microsoft toolchain is not possible, install Python
> 3.12 where pre-built wheels are still distributed and none of the native
> dependencies need compilation.

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
