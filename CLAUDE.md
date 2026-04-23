# Project: microcontroller tools

I'd like to build a set of tools for working with microcontrollers. For starters:

1. A tool to discover devices connected via USB
2. A tool to connect to specific devices via USB and update them with micropython
3. A tool to pull and push new code to the devices
4. A tool to set an ip on a device wireless card if it exists

## Architecture
1. python 3.14
2. Tools will all be command line unless specified

## Code conventions
1. Use doc strings and well document classes methods and functions
2. use dataclass dataclasses for modeling if needed
3. strict typing
4. follow pep standards

## Project conventions
1. keep code in device-type specific directories, ie arduino-nano-esp32

## Things to always do
1. always commit code
2. if there is a better way to do something I have suggested, please suggest that

## Things to never do
1. never commit secrets
