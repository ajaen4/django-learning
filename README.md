# Django Serverless

## Introduction

This project main objective is to provide Django developers an easy way of deploying several Django project.

## Tech Stack

Technologies used:

- Pulumi
- AWS

## Architecture

<p align="center">
  <img src="images/django-serverless.png?raw=true" alt="Architecture">
</p>

Components per Django project:

- 1 Application Load Balancer (ALB)
- 1 ECS Service
    - N tasks per service (parametrized)
- 1 RDS Database

## Requirements

## Requirements

- You must own an AWS account and have an Access Key to be able to authenticate. You need this so every script or deployment is done with the correct credentials. See [here](https://docs.aws.amazon.com/cli/latest/reference/configure/) steps to configure your credentials.

- Versions:
    - Pulumi >=3.0.0,<4.0.0
    - Python = 3.11

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
```
In the case of using Microsoft:

```bash
python3 -m venv .venv
.\env\Scripts\activate
```

And to install all required packages:

```bash
pip install -r requirements.txt
```

## Infrastructure deployment

Navigating to the pulumi directory:

```bash
cd pulumi
pulumi up
```

You will enter a dialog where it will ask you if you want to create a stack. Check the pulumi docs for details.
