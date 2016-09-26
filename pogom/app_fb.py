# -*- coding: utf-8 -*-
from __future__ import division
from . import config
from .app import Pogom
from .utils import get_pokemon_id, get_pokemon_names, get_pokemon_name, get_move_id
from flask import request
from pytz import timezone
from datetime import datetime
from time import time
import logging
import requests
import json
import os
import re

log = logging.getLogger(__name__)
log.setLevel(level=10)


class PogomFb(Pogom):

    def __init__(self, *args, **kwargs):
        super(PogomFb, self).__init__(*args, **kwargs)
        self.route('/fb', methods=['POST'])(self.message_handler)
        self.route('/fb', methods=['GET'])(self.verify)
        # move to model or somewhere
        self._timezone = timezone(config['FB_NOTIFICATION_TIMEZONE'] or 'UTC')
        self._fb_subscribers = config['FB_SUBSCRIBERS'] or {}
        self._fb_noti_history = {}
        for subscriber in self._fb_subscribers.iterkeys():
            self._fb_noti_history[subscriber] = {}

    def verify(self):
        log.info('')
        if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
            if request.args.get("hub.verify_token") == config['FB_VERIFICATION_CODE']:
                return request.args["hub.challenge"], 200
            else:
                return "verification failed", 403
        return "bad request", 400

    def message_handler(self):
        data = request.get_json()
        log.debug('Got msg from fb:{0}'.format(data))

        if data["object"] == "page":
            for entry in data["entry"]:
                for event in entry["messaging"]:
                    if "message" not in event:
                        continue
                    if "text" in event["message"]:
                        self._message_processor(
                            event["sender"]["id"],
                            event["message"]["text"])
                    if "attachments" in event["message"]:
                        for attachment in event["message"]["attachments"]:
                            if attachment.get("type") == "location":
                                coord = attachment["payload"]["coordinates"]
                                self._location_processor(
                                    sender_id=event["sender"]["id"],
                                    lat=coord["lat"], lng=coord["long"])
        return "ok", 200

    def notify(self, found_pokemons):
        for recipient, subscriber_info in self._fb_subscribers.iteritems():
            notify_when_found = subscriber_info['subscription']
            for msg, map_link in self._generate_notify_msg(recipient, notify_when_found, found_pokemons):
                r = requests.get(map_link, stream=True)
                if r.status_code == 200:
                    r.raw.decode_content = True
                    fb_send_message(recipient, img_tuple=('map.jpg', r.raw, 'image/jpeg'))
                else:
                    fb_send_message(recipient, img_url=map_link)
                fb_send_message(recipient, msg)

    def _add_map_location(self, lat, lng, radius):
        if all((lat, lng, radius)):
            self.scan_config.add_scan_location(lat, lng, radius)

    def _del_map_location(self, lat, lng):
        if all((lat, lng)):
            self.scan_config.delete_scan_location(lat, lng)

    def _get_timestamp(self, dt):
        return (dt - datetime(1970, 1, 1)).total_seconds()

    def _is_criteria_matched(self, recipient, pokemon_id, iv, move_1, move_2):
        criteria = self._fb_subscribers[recipient]['additional_criteria']['pokemon_id']
        move1, move2 = get_move_id(move_1), get_move_id(move_2)
        if all((
                iv >= criteria.get('iv', -1),
                criteria.get('move1') == move1,
                criteria.get('move2') == move2)):
            return True
        return False

    def _generate_notify_msg(self, recipient, notify_list, found_pokemons):
        for m in found_pokemons:
            if m["pokemon_id"] not in notify_list:
                continue

            move_1, move_2 = m.get('move_1', ''), m.get('move_2', '')
            atk, dfn, sta = (
                m.get('individual_attack', 0),
                m.get('individual_defense', 0),
                m.get('individual_stamina', 0)
            )
            iv = 100 * (atk + dfn + sta) / 45.0 if any((atk, dfn, sta)) else 0
            if not self._is_criteria_matched(recipient, iv, move_1, move_2):
                continue
            if m["encounter_id"] in self._fb_noti_history[recipient]:
                continue
                # normalize time
                disappear_ts = self._get_timestamp(m['disappear_time'])
                self._fb_noti_history[recipient][m["encounter_id"]] = disappear_ts
                local_time = datetime.fromtimestamp(disappear_ts, self._timezone)
                exp_ctime = "{h:0>2}:{m:0>2}:{s:0>2}".format(
                    h=local_time.hour, m=local_time.minute,
                    s=local_time.second)
                msg = [
                    u"野生的 {pokemon_name} 出現了!",
                    u"消失於: {ctime}"
                ]

                if all((move_1, move_2)):
                    msg.append(u'{m1}/{m2}'.format(
                        m1=move_1, m2=move_2
                    ))

                if iv:
                    msg.append(u'IV: {iv:0.2f}%'.format(iv=iv))
                    msg.append(u'攻: {atk}, 防: {dfn}, 耐: {sta}'.format(atk=atk, dfn=dfn, sta=sta))
                msg = u"\n".join(msg)
                msg = msg.format(
                    pokemon_name=m['pokemon_name'],
                    ctime=exp_ctime
                )
                yield (
                    msg,
                    self._get_map_snippet(longitude=m['longitude'], latitude=m['latitude'])
                )

    def _clear_expired_entries_from_history(self):
        pass

    def _get_map_snippet(self, longitude, latitude):
        map_url = "http://maps.googleapis.com/maps/api/staticmap?center={latitude},{longitude}&zoom=16&scale=1&size=300x300&maptype=roadmap&format=jpg&visual_refresh=true&markers=size:small%7Ccolor:0xff0000%7Clabel:%7C{latitude},{longitude}"
        return map_url.format(longitude=longitude, latitude=latitude)

    def _init_subscriber(self, s_id):
        self._fb_subscribers[s_id] = {}
        self._fb_subscribers[s_id]['subscription'] = []
        self._fb_subscribers[s_id]['additional_criteria'] = {}
        self._fb_subscribers[s_id]['recon'] = None
        self._fb_noti_history[s_id] = {}

    def _subscribe_pokemon(self, s_id, pokemon_id, additional_criteria=None):
        """
        additional_criteria: {'iv':0, 'move_1':'00', blahblah}
        """
        if pokemon_id in self._fb_subscribers[s_id]['subscription'] and additional_criteria is None:
            return "u said"

        if pokemon_id not in self._fb_subscribers[s_id]['subscription']:
            self._fb_subscribers[s_id]['subscription'].append(pokemon_id)
            ret_msg = 'sure bro'
        if additional_criteria:
            criteria = {}
            iv = additional_criteria.get('iv')
            move1 = additional_criteria.get('move1', '')
            move2 = additional_criteria.get('move2', '')
            try:
                criteria['iv'] = float(iv)
            except Exception as e:
                criteria['iv'] = -1
            ret_msg += ', u r asking iv over ' + criteria['iv']
            mid1, mid2 = get_move_id(move1), get_move_id(move2)
            if mid1:
                criteria['move1'] = mid1
                ret_msg += ', move 1 is ' + move1
            if mid2:
                criteria['move2'] = mid2
                ret_msg += ', move 2 is ' + move2

            self._fb_subscribers[s_id]['additional_criteria'][pokemon_id] = criteria
        self._save_subscriber()
        return ret_msg

    def _unsubscribe_pokemon(self, s_id, pokemon_id):
        if pokemon_id in self._fb_subscribers[s_id]['subscription']:
            self._fb_subscribers[s_id]['subscription'].remove(pokemon_id)
            self._fb_subscribers[s_id]['additional_criteria'].pop(pokemon_id)
            self._save_subscriber()
            return "If this is what you want..."
        else:
            return "never heard that!"

    def _get_subscription_list(self, s_id):
        if s_id in self._fb_subscribers:
            return " ".join([get_pokemon_name(n) for n in self._fb_subscribers[s_id]['subscription']])
        else:
            return ""

    def _unsubscribe_all(self, s_id):
        if s_id in self._fb_subscribers:
            self._del_subscriber_location[s_id]
            del self._fb_subscribers[s_id]
        if s_id in self._fb_noti_history:
            del self._fb_noti_history[s_id]
        self._save_subscriber()

    def _save_subscriber(self):
        if (config['CONFIG_PATH'] is not None and os.path.isfile(config['CONFIG_PATH'])):
            config_path = config['CONFIG_PATH']
        else:
            config_path = os.path.join(config['ROOT_PATH'], 'config.json')

        data = json.load(open(config_path, 'r'))
        data['FB_SUBSCRIBERS'] = self._fb_subscribers
        with open(config_path, 'w') as f:
            f.write(json.dumps(data))

    def _move_subscriber_location(self, s_id, lat, lng):
        self._del_subscriber_location(s_id)
        self._add_map_location(lat, lng, 250)
        self._fb_subscribers[s_id]['recon'] = (lat, lng)
        self._save_subscriber()

    def _del_subscriber_location(self, s_id):
        if self._fb_subscribers[s_id]['recon']:
            prev_lat, prev_lng = self._fb_subscribers[s_id]['recon']
            self._del_map_location(prev_lat, prev_lng)
            self._fb_subscribers[s_id]['recon'] = None

    def _location_processor(self, sender_id, lat, lng):
        if sender_id not in self._fb_subscribers:
            self._init_subscriber(sender_id)
        self._move_subscriber_location(sender_id, lat, lng)
        fb_send_message(sender_id, "delivering ur pizzzaa")

    def _message_processor(self, sender_id, msg):
        response_msg = "QQ more"
        if 'forget me' in msg:
            self._unsubscribe_all(sender_id)
            response_msg = "how sad but I will..."
        elif msg.startswith('byebye') or msg.startswith('tell me about'):
            if sender_id not in self._fb_subscribers:
                self._init_subscriber(sender_id)
            response_msg = ''
            if 'byebye' in msg:
                pokemon_name = msg.split('byebye')[1].strip()
                pokemon_id = get_pokemon_id(pokemon_name)
                if pokemon_id:
                    response_msg = self._unsubscribe_pokemon(sender_id, int(pokemon_id))
            else:
                criteria = self._parse_pokemon_subscription_msg(msg)
                pokemon_name = criteria.get('name')
                pokemon_id = get_pokemon_id(pokemon_name)
                if pokemon_id:
                    criteria.pop('name')
                    response_msg = self._subscribe_pokemon(sender_id, int(pokemon_id), criteria)
            if not response_msg:
                response_msg = u"wat's {0}".format(pokemon_name)
        elif msg.startswith('what did i say'):
            response_msg = self._get_subscription_list(sender_id)
            if not response_msg:
                response_msg = 'i know nothing about you, tell me more'
        elif msg.startswith('cancel my flight'):
            self._del_subscriber_location(sender_id)
            self._save_subscriber()
            response_msg = 'oh...'
        elif msg.startswith('pokedex'):
            response_msg = " ".join(get_pokemon_names())
        elif msg.startswith('llist'):
            # for debug
            response_msg = str(self._fb_subscribers[sender_id])
        fb_send_message(sender_id, response_msg)

    def _parse_pokemon_subscription_msg(self, msg):
        msg_segs = re.split('if|and', msg, re.I | re.U)
        pat = "tell me about (?P<name>.*)|iv over (?P<iv>[\d]*)|move1 is (?P<move1>.*)|move2 is (?P<move2>.*)"
        criteria = {}
        for seg in msg_segs:
            res = re.search(pat, seg.strip(), re.I)
            if res:
                criteria.update({k: v for k, v in res.groupdict().iteritems() if v})
        return criteria


def fb_send_message(recipient_id, msg="", img_url="", img_tuple=None):
    def _payload():
        payload = {
            "params": {"access_token": config['FB_TOKEN']}
        }
        if msg or img_url:
            payload['headers'] = {"Content-Type": "application/json"}
            payload['data'] = json.dumps({
                "recipient": {"id": recipient_id},
                "message": {"text": msg_seg} if msg_seg else {
                    'attachment': {'type': 'image', 'payload': {'url': img_url}}}
            })
        else:
            payload['files'] = {'filedata': img_tuple}
            payload['data'] = {
                "recipient": json.dumps({"id": recipient_id}),
                "message": json.dumps({'attachment': {'type': 'image', 'payload': {}}})
            }
        return payload

    def _send():
        r = requests.post("https://graph.facebook.com/v2.6/me/messages", **_payload())
        log.info(u"reply sent: {0}:{1}:{2}".format(r.status_code, r.text, img_url))
        if r.status_code != 200:
            log.debug("send message failed: {0}".format(r.status_code))

    seg_size = 120
    if len(msg) > seg_size:
        segs = len(msg) // seg_size
        i = 0
        for i in xrange(1, segs + 1):
            msg_seg = msg[(i - 1) * seg_size:i * seg_size]
            _send()
        if len(msg) % seg_size != 0:
            msg_seg = msg[i * seg_size:]
            _send()
    else:
        msg_seg = msg
        _send()

# msg = u"tell me about 迷你龍 if iv over 30 and move1 is Dragon Breath and move2 is Hydro Bump"
# msg = u"tell Me about dratini if move1 is Dragon Breath and iv over 30"
