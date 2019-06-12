import logging
import os
import subprocess

import flask
import requests
import waitress
import yaml
from matrix_client.api import MatrixHttpApi

CONFIG_DIR = os.environ.get("MATRIX_APPSERVICE_LEDGER_CONFIG_DIR", "../config/")
CONFIG_FILE = os.environ.get("MATRIX_APPSERVICE_LEDGER_CONFIG_FILE", "ledger-registration.yaml")
CONFIG_PATH = os.path.join(CONFIG_DIR, CONFIG_FILE)
ALLOWED_USERS = os.environ.get("MATRIX_APPSERVICE_LEDGER_USERS", None).split(',')

logging.basicConfig(
    format='%(asctime)s | %(levelname)-8s | %(threadName)-22s | %(message)s',
    level=logging.DEBUG
)

logger = logging.getLogger(__name__)

if None in [CONFIG_DIR, CONFIG_FILE, ALLOWED_USERS]:
    raise ValueError("Missing environment variable. Cannot continue.")

with open(CONFIG_PATH, 'r') as stream:
    try:
        config = yaml.safe_load(stream)
        AS_TOKEN = config["as_token"]
        HS_TOKEN = config["hs_token"]
        HS_URL = config["hs_url"]
        logger.debug(f"Loaded config: {config}")
    except KeyError as ke:
        raise ValueError(f"Cannot find key {ke} in configuration file.")
    except yaml.YAMLError as ye:
        raise

app = flask.Flask(__name__)
matrix = MatrixHttpApi(HS_URL, token=AS_TOKEN)


@app.route("/transactions/<txn_id>", methods=["PUT"])
def on_receive_events(txn_id):
    events = flask.request.get_json()["events"]
    for event in events:
        user_id = event['user_id']
        room_id = event['room_id']
        type = event['type']
        content = event['content']
        members = get_joined_room_members(room_id)

        logger.debug(f"User: {user_id} Room: {room_id}")
        logger.debug(f"Event Type: {type}")
        logger.debug(f"Content: {content}")
        logger.debug(f"The room has {len(members)} members in it: {', '.join(members.keys())}.")

        if user_id in ALLOWED_USERS and type == 'm.room.message':
            body = content['body']
            if len(members) == 2:
                data = None
                if body.startswith('!echo '):
                    message = content['body'][6:]
                    logger.info(f"Echoing message '{message}' to room {room_id}")
                    matrix.join_room(room_id)
                    data = message_event(message)
                elif body.startswith('!sh '):
                    command = content['body'][4:]
                    try:
                        result = shell(command)
                        data = message_event(result, f"<pre>{result}</pre>")
                    except subprocess.CalledProcessError as cpe:
                        logger.warning(cpe)
                        data = message_event(f"command failed: {cpe}")
                    except subprocess.TimeoutExpired as te:
                        logger.warning(te)
                        data = message_event(f"command timed out: {te}")
                elif body.startswith('!ledger '):
                    ledger_command = content['body'][8:]
                    try:
                        result = shell(ledger_command)
                        data = message_event(result, f"<pre>{result}</pre>")
                    except subprocess.CalledProcessError as cpe:
                        logger.warning(cpe)
                        data = message_event(f"command failed: {cpe}")
                    except subprocess.TimeoutExpired as te:
                        logger.warning(te)
                        data = message_event(f"command timed out: {te}")
                if data:
                    matrix.send_message_event(room_id, "m.room.message", data)
            else:
                matrix.send_message(room_id,
                                    "I'm sorry, but this is not a private room so I'm not going to do that.")
        logger.debug("------------------------------------------------------------------")

    return flask.jsonify({})


def message_event(body, formatted_body=None) -> dict:
    me = {
        "format": "org.matrix.custom.html",
        "msgtype": "m.text",
        'body': body
    }
    if formatted_body:
        me['formatted_body'] = formatted_body

    return me


def shell(command) -> str:
    cmd = [
        "/bin/sh",
        "-c",
        command
    ]
    return subprocess.check_output(cmd, timeout=13).decode()


def get_joined_room_members(room_id) -> dict:
    url = f"{HS_URL}/_matrix/client/r0/rooms/{room_id}/joined_members?access_token={AS_TOKEN}"
    get = requests.get(url)
    return get.json()['joined']


if __name__ == "__main__":
    waitress.serve(app)