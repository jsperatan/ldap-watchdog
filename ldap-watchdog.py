#!/usr/bin/env python3

# This file is an original work developed by Joshua Rogers<https://joshua.hu/>.
# Licensed under the GPL3.0 License.  You should have received a copy of the GNU General Public License along with LDAP Watchdog. If not, see <https://www.gnu.org/licenses/>.

import json
import os
import sys
from datetime import datetime
import time
import requests

import re
from ldap3 import Server, Connection, ALL, SUBTREE
from ldap3.core.exceptions import LDAPSocketOpenError

CONTROL_UUID = ''
CONTROL_USER_ATTRIBUTE = ''

# LDAP_SERVER = os.getenv('LDAP_SERVER')
LDAP_SERVER =  'ldap://172.30.173.208:389'
LDAP_USERNAME = 'cn=admin,dc=example,dc=org'
# LDAP_USERNAME = os.getenv('LDAP_USERNAME')
LDAP_PASSWORD = os.getenv('LDAP_PASSWORD')
LDAP_PASSWORD = LDAP_PASSWORD.replace("\n", "")
LDAP_USE_SSL = False
BASE_DN = 'dc=example,dc=org'

DISABLE_COLOR_OUTPUT = False

SEARCH_FILTER = '(&(|(objectClass=inetOrgPerson)(objectClass=groupOfNames)))'
SEARCH_ATTRIBUTE = ['*', '+']

REFRESH_RATE = 10

SLACK_BULLETPOINT = ' \u2022   '

IGNORED_UUIDS = []
IGNORED_ATTRIBUTES = []

CONDITIONAL_IGNORED_ATTRIBUTES = {}

SLACK_WEBHOOK = os.getenv('SLACK_WEBHOOK_URL', '')

# The API endpoint to call when a new user is created
API_ENDPOINT = os.getenv('API_ENDPOINT')
TOKEN = os.getenv('TOKEN')
TOKEN = TOKEN.replace("\n", "")

if SLACK_WEBHOOK and len(SLACK_WEBHOOK) > 0:
    import requests

def col(op_type):
    """
    Returns ANSI color codes for different LDAP operation types.

    Parameters:
    - op_type (str): LDAP operation type ('add', 'delete', 'modify').

    Returns:
    - str: ANSI color code.
    """
    if DISABLE_COLOR_OUTPUT:
        return ''
    return {'add': "\033[1m\033[32m", 'delete': "\033[3m\033[31m", 'modify': "\033[33m"}[op_type]


def call_api(new_user_dn):
    """
    Calls an API endpoint when a new user is created in the LDAP directory.
    """
    match = re.search(r'uid=([^,]+)', new_user_dn)
    user = match.group(1)

    headers = {
    "Content-Type": "application/json",
    "Authorization": "Basic " + TOKEN,
    # "ECM-CS-XSRF-Token": "123",
}
    
    with requests.Session() as session:
        query = f"""
 mutation{{
  topfolder: createFolder(
    repositoryIdentifier: "CONTENT"
    folderProperties:{{
        name:"{user} Personal Folder"
        parent:{{
          identifier:"/"
        }}
      permissions:{{
        replace:[
          {{
            type:ACCESS_PERMISSION
            inheritableDepth:OBJECT_ONLY
            accessMask:999415
            subAccessPermission:{{
              accessType:ALLOW
              granteeName:"{user}"
            }}
          }}
        ]
      }}
      }}
    )
    {{name
      className
      pathName
    }}
  }}
"""
    payload = {
        "query": query
    }

    r = session.post(API_ENDPOINT, headers=headers, json=payload, verify=False)
    print(r.json()) 

def retrieve_ldap():
    """
    Connects to the LDAP server and retrieves LDAP entries.

    Returns:
    - dict: Dictionary containing LDAP entries.
    """
    entries = {}
    server = Server(LDAP_SERVER, use_ssl=LDAP_USE_SSL, get_info=ALL)
    if LDAP_USERNAME and LDAP_PASSWORD:
        conn = Connection(server, user=LDAP_USERNAME, password=LDAP_PASSWORD)
        if not conn.bind():
            print('Error in bind:', conn.result, file=sys.stderr)
            return entries
    else:
        conn = Connection(server)
        if not conn.bind():
            print('Anonymous bind failed:', conn.result, file=sys.stderr)
            return entries

    conn.search(search_base=BASE_DN, search_filter=SEARCH_FILTER, search_scope=SUBTREE, attributes=SEARCH_ATTRIBUTE)

    for entry in conn.entries:
        entry = json.loads(entry.entry_to_json())
        entry_dict = entry['attributes']
        for attr_name, attr_value in entry_dict.items():
            attr_value = attr_value[0]
            # Some entries may be encoded using base64 and provided by a dictionary.
            # In that case, replace the dictionary with a string of the encoded data.
            if isinstance(attr_value, dict) and len(attr_value) == 2 and 'encoded' in attr_value and 'encoding' in attr_value and attr_value['encoding'] == 'base64':
                decoded_value = attr_value['encoded']
                entry_dict[attr_name] = decoded_value

        entry_dict['dn'] = [entry['dn']]
        entries[entry_dict['entryUUID'][0]] = entry_dict

    return entries

def generate_message(dn_uuid, op_type, changes):
    """
    Generates formatted messages for Slack and console output based on LDAP changes.

    Parameters:
    - dn_uuid (str): LDAP entry's UUID.
    - op_type (str): LDAP operation type ('add', 'delete', 'modify').
    - changes (dict): Dictionary containing LDAP attribute changes.

    Returns:
    - tuple: (str, str) Tuple containing Slack and console-formatted messages.
    """
    now = datetime.now()
    timestamp = now.strftime('%d/%m/%Y %H:%M:%S')

    rst_col = "\033[0m"
    stt_col = "\033[1m\033[35m"
    if DISABLE_COLOR_OUTPUT:
        rst_col = ""
        stt_col = ""

    bl = f"{SLACK_BULLETPOINT}{op_type}"

    slack_msg = f"*[{timestamp}] {op_type} {dn_uuid}*\n"
    print_msg = f"[{stt_col}{timestamp}{rst_col}] {op_type}{col(op_type)} {dn_uuid}{rst_col}\n"

    if op_type == 'modify':
        for additions in changes['additions']:
            for key, vals in additions.items():
                for val in vals:
                    slack_msg += f"{SLACK_BULLETPOINT}add *'{key}'* to *'{val}'*\n"
                    print_msg += f"{SLACK_BULLETPOINT}add '{col('modify')}{key}{rst_col}' to '{col('add')}{val}{rst_col}'\n"
        for removals in changes['removals']:
            for key, vals in removals.items():
                for val in vals:
                    slack_msg += f"{SLACK_BULLETPOINT}delete *'{key}'* was _'{val}'_\n"
                    print_msg += f"{SLACK_BULLETPOINT}delete '{col('modify')}{key}{rst_col}' was '{col('delete')}{val}{rst_col}'\n"
        for modifications in changes['modifications']:
            for key, val in modifications.items():
                slack_msg += f"{SLACK_BULLETPOINT}modify *'{key}'* to *'{val[1]}'* was _'{val[0]}'_\n"
                print_msg += f"{SLACK_BULLETPOINT}modify '{col('modify')}{key}{rst_col}' to '{col('add')}{val[1]}{rst_col}' was '{col('delete')}{val[0]}{rst_col}'\n"
    elif op_type == 'delete':
        for key, vals in changes.items():
            for val in vals:
                slack_msg += f"{bl} *'{key}'* was _'{val}'_\n"
                print_msg += f"{bl} '{col('modify')}{key}{rst_col}' was '{col('delete')}{val}{rst_col}'\n"
    elif op_type == 'add':
        for key, vals in changes.items():
            for val in vals:
                slack_msg += f"{bl} *'{key}'* to *'{val}'*\n"
                print_msg += f"{bl} '{col('modify')}{key}{rst_col}' to '{col('add')}{val}{rst_col}'\n"

    return slack_msg, print_msg


def announce(dn_uuid, op_type, changes):
    """
    Sends notification messages to Slack and prints to the console.

    Parameters:
    - dn_uuid (str): LDAP entry's UUID.
    - op_type (str): LDAP operation type ('add', 'delete', 'modify').
    - changes (dict): Dictionary containing LDAP attribute changes.

    Returns:
    - None
    """
    slack_msg, print_msg = generate_message(dn_uuid, op_type, changes)
    send_to_slack(slack_msg)
    print(print_msg)


def truncate_slack_message(message):
    """
    Truncates long Slack messages to fit within the character limit.

    Parameters:
    - message (str): Slack message.

    Returns:
    - str: Truncated Slack message.
    """
    while len(message) > 4000:
        longest_word = max(message.split(), key=len)
        message = message.replace(longest_word, "[...truncated...]")

    return message


def send_to_slack(message):
    """
    Sends a formatted message to Slack.

    Parameters:
    - message (str): Formatted message.

    Returns:
    - None
    """
    if SLACK_WEBHOOK is None or len(SLACK_WEBHOOK) == 0:
        return

    message = truncate_slack_message(message)

    headers = {'Content-type': 'application/json'}
    data = {'text': message}
    requests.post(SLACK_WEBHOOK, headers=headers, data=json.dumps(data))


def check_control_user(old_entries, new_entries):
    """
    Checks if the control user's LDAP entry has changed.

    Parameters:
    - old_entries (dict): Dictionary containing old LDAP entries.
    - new_entries (dict): Dictionary containing new LDAP entries.

    Returns:
    - bool: True if the control user's entry has changed, False otherwise.
    """
    control_user_found = False
    if CONTROL_UUID not in new_entries or CONTROL_UUID not in old_entries:
      return control_user_found

    new_entry = new_entries[CONTROL_UUID]
    old_entry = old_entries[CONTROL_UUID]

    if CONTROL_USER_ATTRIBUTE and len(CONTROL_USER_ATTRIBUTE) > 0:
        # If using CONTROL_USER_ATTRIBUTE, only compare that attribute as long as it exists in both new_entry and old_entry.
        if CONTROL_USER_ATTRIBUTE in new_entry and CONTROL_USER_ATTRIBUTE in old_entry and new_entry[CONTROL_USER_ATTRIBUTE] != old_entry[CONTROL_USER_ATTRIBUTE]:
          control_user_found = True
    else:
        # Otherwise, check that at least one attribute has changed, regardless of what it is.
        for new_attribute in new_entry.keys():
            if new_attribute in old_entry and old_entry[new_attribute] != new_entry[new_attribute]:
                control_user_found = True
                break

    return control_user_found


def compare_ldap_entries(old_entries, new_entries):
    """
    Compares old and new LDAP entries and announces modifications.

    Parameters:
    - old_entries (dict): Dictionary containing old LDAP entries.
    - new_entries (dict): Dictionary containing new LDAP entries.

    Returns:
    - None
    """
    if len(CONTROL_UUID) > 0 and not check_control_user(old_entries, new_entries):
        print('Could not confirm the control user change.', file=sys.stderr)
        return

    # XXX: The next four lines of code do not consider ignored UUIDs or ignored attributes.
    for uuid in old_entries.keys() - new_entries.keys():
        # Any entries that are in old_entries but not new_entries are deletions.
        announce(f"{old_entries[uuid]['dn'][0]} ({old_entries[uuid]['entryUUID'][0]})", "delete", old_entries[uuid])

    for uuid in new_entries.keys() - old_entries.keys():
        # New entry means a user has been created
        new_entry = new_entries[uuid]
        if "inetOrgPerson" in new_entry["objectClass"]:
            # Call the API when a new user is created
            call_api(new_entry["dn"][0])
        # Any entries that are in new_entries but not old_entries are additions.
        announce(f"{new_entries[uuid]['dn'][0]} ({new_entries[uuid]['entryUUID'][0]})", "add", new_entries[uuid])

    for uuid in old_entries.keys() & new_entries.keys():
        if uuid in IGNORED_UUIDS:
            continue  # TODO: print that it was skipped?
        if old_entries[uuid] != new_entries[uuid]:
            # For changes of a user, there are three types of operations to define: additions, removals, and modifications.
            changes = {}
            # XXX: Could these be dictionaries instead?
            changes.setdefault("additions", []) # A list of addition of values to attributes.
            changes.setdefault("modifications", []) # A list of changes of a single value for an attribute.
            changes.setdefault("removals", []) # A list of removal of values from an atttribute.
            for key in old_entries[uuid].keys() | new_entries[uuid].keys():
                # Compare each key (attribute) in the old and new entries
                old_value = old_entries[uuid].get(key)
                new_value = new_entries[uuid].get(key)
                # If they are not the same, we have some type of change.
                if old_value != new_value:
                    if old_value is None:
                        # If the key is not found in old_entries, it's an addition.
                        changes["additions"].append({key: new_value})
                    elif new_value is None:
                        # If the key is not found in new_entries, it's a removal.
                        changes["removals"].append({key: old_value})
                    else:
                        # If the key is in both old_entries and new_entries but the values are not the same, then may be a modification.
                        # There is no way to truly determine whether an attribute's value(s) have been changed, or removed and then a new value added.
                        # Therefore, we define a modification as the change of an attribute that has only a single value.
                        if len(old_value) == len(new_value) == 1:
                            changes["modifications"].append({key: (old_value[0], new_value[0])})
                        else:
                            # If there is either zero or more than one value for an attribute, then the difference beteen the old values and the new values indicate an addition or removal (or a value; not an entry).
                            # That is to say: this is the addition or removal of values for an attribute which does not have exactly one old value and exactly one new value.
                            # Therefore, if a new value (or values) is present for an attribute, it is also an addition.
                            added = set(new_value) - set(old_value)
                            # And if the value (or values) is only in the old data, it is a removal.
                            removed = set(old_value) - set(new_value)
                            if added:
                                changes["additions"].append({key: added})
                            if removed:
                                changes["removals"].append({key: removed})

            # It is worth remembering what "changes" really is.
            #
            # changes["modifications"] is a set of dictionaries. Each dictionary's key is an attribute name, and the value is a tuple of (old_ldap_value, new_ldap_value).
            # changes["modifications"] =
            # [
            #   { attr_name: (old_val, new_val) },
            #   { attr_name2: (old_val2, new_val2) },
            # ]
            #
            # changes["additions"] and changes["removals"] are each a set of dictionaries. Each dictionary's key is an attribute name, and the value is a set of the values for which we wish to ignore.
            # changes["additions"] =
            # [
            #  { attr_name: [val1, val2] },
            #  { attr_name2: [val1, val2] },
            # ]

            for change_type in ["additions", "modifications", "removals"]:
                for ignored_attr_name in IGNORED_ATTRIBUTES:
                    for change in changes[change_type][:]:  # Using a shallow copy of each dictionary.
                        # For each change type, check whether any of the changed attribute names should be ignored.
                        if ignored_attr_name in change:
                            print(f"Ignoring {old_entries[uuid]['dn'][0]} ({old_entries[uuid]['entryUUID'][0]}) {change}", file=sys.stderr)
                            changes[change_type].remove(change)

            for change_type in ["additions", "modifications", "removals"]:
                for ignored_attr_name, ignored_attr_list in CONDITIONAL_IGNORED_ATTRIBUTES.items():
                    for change in changes[change_type][:]: # 'change' is each dictionary in changes[change_type].
                        if ignored_attr_name in change: # Check if the ignored attribute is in the dictionary
                            if change_type == "modifications": # For modifications, we ignore the change if either the new or old value of the ignored attribute is the ignored value.
                                old_attr_value = change[ignored_attr_name][0] # old value
                                new_attr_value = change[ignored_attr_name][1] # new value
                                if old_attr_value in ignored_attr_list or new_attr_value in ignored_attr_list:
                                    print(f"Ignoring {change_type} of {old_entries[uuid]['dn'][0]} ({old_entries[uuid]['entryUUID'][0]}) {ignored_attr_name}: from {old_attr_value} to {new_attr_value}", file=sys.stderr)
                                    changes[change_type].remove(change) # Remove the whole dictionary from changes["modifications"].
                            else:
                                for added_or_removed_val in change[ignored_attr_name][:]: # val1, val2, ...
                                    if added_or_removed_val in ignored_attr_list: # Check whether the value should be ignored.
                                        print(f"Ignoring {change_type} of {old_entries[uuid]['dn'][0]} ({old_entries[uuid]['entryUUID'][0]}) {ignored_attr_name}: {added_or_removed_val}", file=sys.stderr)
                                        change[ignored_attr_name].remove(added_or_removed_val) # Remove the ignored value from the set of added/removed attributes for attribute ignored_attr_name.
                                        if len(change[ignored_attr_name]) == 0: # If the added/removed attribute set for ignored_attr_name is in now empty ( {attr_name: []} ) then delete it.
                                            changes[change_type].remove(change)

            for change_type in ["additions", "modifications", "removals"]:
                if len(changes[change_type]) > 0:
                    announce(f"{old_entries[uuid]['dn'][0]} ({old_entries[uuid]['entryUUID'][0]})", "modify", changes)
                    break


if __name__ == '__main__':
    new_entries = retrieve_ldap()
    print("Starting LDAP Watchdog Service...")
    while True:
        time.sleep(REFRESH_RATE)
        print("Monitoring for LDAP changes...")

        try:
            retrieved_entries = retrieve_ldap()
        except LDAPSocketOpenError as e:
            print(f"LDAP connection error: {e}", file=sys.stderr)
            continue

        old_entries = new_entries
        new_entries = retrieved_entries
        compare_ldap_entries(old_entries, new_entries)
