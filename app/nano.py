import json
import logging
import os

import jinja2
import requests

from app.config import HOST, EMAIL_ENABLED
from app.ses import send

logger = logging.getLogger(__name__)

history_data = {
    'action': 'account_history'
}
pending_data = {
    'action': 'pending',
    'source': 'true'
}


def get_trans_history(account, count):
    req = dict(account=account, count=count, **history_data)
    return requests.post(f'http://{HOST}:7076', json.dumps(req)).json().get('history', [])


def get_pendings(account):
    req = dict(account=account, **pending_data)
    pending = requests.post(f'http://{HOST}:7076', json.dumps(req)).json()
    return pending['blocks'] if pending.get('blocks') else {}


def notify(emails, message, subject, from_email):
    if EMAIL_ENABLED:
        logger.debug(f'Sending emails to {str(emails)}')
        logger.debug(f'{subject}\n\n{message}')
        for email in emails:
            send(email, subject, message, from_email)
    else:
        logger.info(subject)
        logger.info(message)


def find_new_pending_trans(all_pending, last_known_pending):
    new_pending = {}
    for tran_hash in all_pending.keys():
        if not last_known_pending.get(tran_hash):
            new_pending[tran_hash] = all_pending[tran_hash]

    logger.debug(f'Found new pending transactions {json.dumps(new_pending, indent=4, sort_keys=True)}')
    return new_pending


def find_newest_trans(account, last_known_trans, count=10):
    trans_history = get_trans_history(account, count)
    new_trans = []
    for tran in trans_history:
        if tran['hash'] != last_known_trans:
            new_trans.append(tran)
        else:
            return new_trans
    # Recursively search until all newest_transactions found
    return find_newest_trans(account, last_known_trans, count=count+10)


def check_account_for_new_transactions(account, last_known_trans, emails):
    logger.info(f'Finding new transactions for {account}')
    # Get last transaction if none
    if not last_known_trans:
        logger.debug(f'No known transactions for {account}')
        history = get_trans_history(account, 10)
        return history[0].get('hash') if history else None

    new_trans = find_newest_trans(account, last_known_trans)
    logger.debug(f'Found new transactions {json.dumps(new_trans, indent=4, sort_keys=True)}')
    message, total = build_message_and_total_for_new_transactions(account, new_trans)
    if message:
        subject = 'Received {total:1.5f} XRB from {account}'.format(total=total, account=account)
        notify(emails, message, subject, from_email='received@nanotify.co')
    return last_known_trans if not new_trans else new_trans[0].get('hash')


def check_account_for_new_pending(account, last_known_pendings, emails):
    logger.info(f'Finding pending transactions for {account}')
    # Get last transaction if none
    pendings = get_pendings(account)
    if any(last_known_pendings):
        logger.debug(f'No known pending transactions for {account}')
        new_pendings = find_new_pending_trans(pendings, last_known_pendings)
    else:
        new_pendings = pendings

    logger.debug(f'No known pending transactions for {account}')
    message, total = build_message_and_total_for_pending_transactions(account, new_pendings)
    if total:
        subject = 'Pending {total:1.5f} XRB from {account}'.format(total=total, account=account)
        notify(emails, message, subject, from_email='pending@nanotify.co')
    return pendings


def build_message_and_total_for_new_transactions(account, new_trans):
    account_transactions = []
    total = 0
    for tran in new_trans:
        if tran['type'] == 'receive':
            from_account = tran['account']
            amount = float(tran['amount'])
            if amount != 0:
                amount /= 1.0e+30
            total += amount
            account_transactions.append({'from_account': from_account, 'amount': amount})
    message = render('templates/transactions_email.html', {'transactions': account_transactions, 'account': account})
    return message, total


def build_message_and_total_for_pending_transactions(account, pendings):
    account_pendings = []
    total = 0
    for tran in pendings.values():
        from_account = tran['source']
        amount = float(tran['amount'])
        if amount != 0:
            amount /= 1.0e+30
        total += amount
        account_pendings.append({'from_account': from_account, 'amount': amount})
    message = render('templates/pendings_email.html', {'transactions': account_pendings, 'account': account})
    return message, total


def format_nano(nano):
    return '{nano:1.5f}'.format(nano=nano)


def render(tpl_path, context):
    path, filename = os.path.split(tpl_path)
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(path or './'))
    env.filters['format_nano'] = format_nano
    return env.get_template(filename).render(context)
