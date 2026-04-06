# kellerkompanie-ts3bot

This project is a automated bot for Teamspeak3 that connects the Kellerkompanie backend with Teamspeak.

## Installation

### Requirements

* Python 3.13 or higher

### Create ts3bot user

Create user with disabled-login

```
sudo adduser --disabled-login ts3bot
```

## Development

### Prerequisites

* [uv](https://docs.astral.sh/uv/) (Python package manager)
* Python 3.14 or higher (uv will install it automatically if missing)
* MariaDB client libraries (`libmariadb-dev` on Debian/Ubuntu, `mariadb-connector-c` on macOS via Homebrew)

### Setup

Clone the repository and install all dependencies:

```
git clone <repo-url>
cd kellerkompanie-teamspeak3-bot
uv sync
```

This creates a virtual environment in `.venv/` and installs the project in editable mode with all dependencies locked
via `uv.lock`.

### Running

```
uv run keko-bot --config configs/keko-ts3bot.yaml
```

### Managing dependencies

```
uv add <package>        # add a new dependency
uv remove <package>     # remove a dependency
uv sync                 # re-sync environment from lockfile
uv lock --upgrade       # upgrade all dependencies
```

### Building

To build a `.deb` package for deployment:

```
uv run scripts/build_deb.py
```
