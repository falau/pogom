## Configuration

Fill in fields at `pogom/pogom/__init__.py`:
- `FB_VERIFICATION_CODE`: 'FB_CODE', # Facebook verification code
- `FB_TOKEN`: 'FB_TOKEN', # Facebook page token
- `FB_NOTIFICATION_TIMEZONE`': 'timezone'  # Recipients' timezone in pytz format

**Note: This implementation doesn't handle SSL, please set a SSL termination in front of it.**

## Commands
- `tell me about {{pokemon_name}}`: Subscribe notification of all scanned {{pokemon_name}}
- `tell me about {{pokemon_name}} if {{criteria_1}} and {{criteria_2}} and ...`: Set additional criteria
  Criteria:
  - `iv over {{number}}`
  - `move1 is {{move name}}`
  - `move2 is {{move name}}`

  e.g. 
    - _tell me about Dragonite if move1 is Dragon Breath and move2 is Dragon Claw and iv over 85_
    - _tell me about Exeggutor if move2 is Solar Beam_
    - _tell me about Eevee if iv over 82_
- `byebye {{pokemon_name}}`: Unsubscribe for certain pokemon
- `forget me`: Unsubscribe for all notifications
- `pokedex`: List subscrible pokemon names
- `what did i say`: List subscriptions
- `Send location via Messenger APP`: Add a scan circle with 250m radius at location sent
- `cancel my flight`: Remove the scan circle set with messenger
- 'llist': Debug message
