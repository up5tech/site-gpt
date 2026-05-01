# SiteGPT

SiteGPT is a system auto generate to Chat Bot for company. It allows users to create and manage their own websites, extra documents, and use them to create a Chat Bot.

## Features

- User authentication and management
- Website management
- Extra document management for additional information
- Use Website information and Extra Document to create a Chat Bot

## Installation

1. Clone the repository
2. Create database
3. Config .env: copy from .env.example
4. Install poetry
5. Run `poetry install`
6. Run `poetry run alembic upgrade head` to apply database migrations
7. Run `poetry run uvicorn src.site_gpt.app.main:app`
8. Run `poetry run python -m src.site_gpt.app.worker` to start the worker

## Development

- Create migration `poetry run alembic revision --autogenerate -m "[name]"`
- Run `poetry run alembic upgrade head` to apply database migrations
- Run `poetry run uvicorn src.site_gpt.app.main:app --reload` to start the development server
