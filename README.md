# SiteGPT

SiteGPT is a system auto generate to Chat Bot for company. It allows users to create and manage their own websites, extra documents, and use them to create a Chat Bot.

![Example](./site-gpt.png)

## Features

- User authentication and management
- Website management
- Extra document management for additional information
- Use Website information and Extra Document to create a Chat Bot

## Installation

- Clone the repository
- Create database
- Install and config redis
- Config .env: copy from .env.example
- Install uv
- Run `uv venv --python 3.13`
- Run `source .venv/bin/activate`
- Run `uv sync`
- Run `uv run alembic upgrade head` to apply database migrations
- Run `uv run uvicorn site_gpt.app.main:app`
- Run `uv run python -m site_gpt.app.worker` to start the worker

## Development

- Create migration `uv run alembic revision --autogenerate -m "[name]"`
- Run `uv run alembic upgrade head` to apply database migrations
- Run `uv run uvicorn site_gpt.app.main:app --reload` to start the development server
