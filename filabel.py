import click
import colorama
import configparser
import requests
import sys
import json
import pprint
from flask import Flask
from flask import render_template
from flask import request
import fnmatch
import os
import hmac
import hashlib

app = Flask(__name__)


def get_conf_files():
    """
    Get names of both of the configuration files
    """
    ret_files = {'cred': '', 'label': ''}
    cvar = os.getenv('FILABEL_CONFIG')
    if cvar == None:
        False
    # Test if there are more conf files
    cvar = cvar.split(':')
    if len(cvar) != 2:
        return False
    
    for fn in cvar:
        with open(fn) as f:
            config = configparser.ConfigParser()
            config.read_file(f)
            if config.has_section('github'):
                ret_files['cred'] = fn
            elif config.has_section('labels'):
                ret_files['label'] = fn   

    if (ret_files['cred'] == '') or (ret_files['label'] == ''):
        return False
    return ret_files


@app.route('/', methods=['GET'])
def show_main_page():
    """
    Show main page '/' to GET method. 
    """
    filenames = get_conf_files()
    if filenames == False:
        return '', 500
    r = ''
    with open(filenames['label']) as f:
        r = get_label_patterns(f)
        if r == False:
            r = {'X': 'No label configuration supplied!'}
    username = get_username(filenames['cred'])
    if username == False:
        username = 'Unable to get'
    return render_template('main.html', name=username, rules = r)


def get_username(conf):
    """
    Get username of the token's owner.
    """
    sesison = requests.Session()
    with open(conf) as f:
        session = create_session(f)
    if session == False:
        return False
    u = session.get('https://api.github.com/user')
    u_json = u.json()
    if 'login' not in u_json:
        return False
    return u_json['login']


@app.route('/', methods=['POST'])
def react_to_post():
    """
    React to POST method - find if it came from GitHub 
    and if it was sent by the corrent event
    """
    payload_headers = request.headers
    if 'X-GitHub-Event' not in payload_headers:
        return
    payload_json = request.get_json()
    if payload_headers['X-GitHub-Event'] == 'ping':
        if handle_ping(payload_headers) == False:
            app.logger.info('ping fail')
            return '', 404
        return '', 200
    elif payload_headers['X-GitHub-Event'] == 'pull_request':
        if handle_pull_request(payload_headers, payload_json['pull_request']) == False:
            return '', 501
        return '', 200
    else:
        return '', 500


def handle_ping(headers):
    """
    Answer to the ping request
    """
    if check_signature(headers) == False:
        return False
    return True


def handle_pull_request(headers, pj):
    """
    Answer to the PR request and change the labels
    """
    if check_signature(headers) == False:
        return False
    filenames = get_conf_files()
    if filenames == False:
        print('Unable to get config files', file=sys.stderr)
        return False
    session = requests.Session()
    with open(filenames['cred']) as f:
        s = create_session(f)
        if s == False:
            print('Unable to open session', file=sys.stderr)
            return False
        session = s
    repo_name = get_repo_name(pj)
    if repo_name == False:
        return False
    pull_num = pj['number']
    labels_current = get_current_labels(pj['labels'])
    pull_filenames = get_pr_files(repo_name, session, pull_num)
    if pull_filenames == False:
        print(f'Unable to get the list of filenames of repo: {repo_name}, pull number: {pull_num}', file=sys.stderr)
        return False
    fpatterns = {}
    with open(filenames['label']) as f:
        fpatterns = get_label_patterns(f)
        if fpatterns == False:
            print('Unable to get list of patterns', file=sys.stderr)
            return False
    labels_new = get_all_labels(pull_filenames, fpatterns) 
    u_labels_to_keep = get_unknown_labels_to_keep(labels_current, fpatterns)
    labels_to_add = labels_new
    labels_to_add += u_labels_to_keep
    labels_to_add = list(set(labels_to_add))
    fl = add_labels(repo_name, pull_num, labels_to_add, session)     
    if fl == False:
        print('Unable to add labels', file=sys.stderr)
        return False
    return True

    
def get_repo_name(p_json):
    """
    Get name of the current repository
    """
    if 'base' not in p_json:
        print('No "base" in pull request payload', file=sys.stderr)
        return False
    if 'repo' not in p_json['base']:
        print('No "repo" in pull request payload', file=sys.stderr)
        return False
    if 'full_name' not in p_json['base']['repo']:
        print('No "full_name" in pull request payload', file=sys.stderr)
        return False
    return p_json['base']['repo']['full_name']



def check_signature(headers):
    """
    Verify the X-Hub-Signature
    """
    secret = get_secret()
    if secret == False:
        return False
    if 'X-Hub-Signature' not in headers:
        print('no signature')
        return False
    sig = headers['X-Hub-Signature']
    sha_name, signature = sig.split('=')
    if sha_name != 'sha1':
        print('wrong hashfunction')
        return False
    s = bytearray(secret, 'utf8')
    m = request.data
    h = hmac.new(s, msg=m, digestmod=hashlib.sha1)
    my_signature = h.hexdigest()
    if hmac.compare_digest(my_signature, signature) == False:
        print(f'secret: {s}\nmsg: {m}\nsig: {signature}\nmy: {my_signature}', file=sys.stderr)
        return False     
    return True

def get_secret():
    """
    Read the webhook secret from configuration file
    """
    conf_files = get_conf_files()
    if conf_files == False:
        return ''
    config = configparser.ConfigParser()
    ret = False
    with open(conf_files['cred']) as f:
        config.read_file(f)
        if config.has_section('github') == False:
            return False
        opts = config.options('github')
        for o in opts:
            if o == 'secret':
                ret = config.get('github', o)
    return ret


token = 'abc'


class color:
   PURPLE = '\033[95m'
   CYAN = '\033[96m'
   DARKCYAN = '\033[36m'
   BLUE = '\033[94m'
   GREEN = '\033[92m'
   YELLOW = '\033[93m'
   RED = '\033[91m'
   BOLD = '\033[1m'
   UNDERLINE = '\033[4m'
   END = '\033[0m'


def get_auth(f):
    """Get authentication token from config file"""
    config = configparser.ConfigParser()
    config.read_file(f)
    if config.has_section('github') == False:
        return False
    opts = config.options('github')
    ret = ''
    for o in opts:
        if o == 'token':
            ret = config.get('github', o)
    if ret == '':
        return False
    return ret


def token_auth(req):
    """Helper function for the session"""
    req.headers['Authorization'] = f'token {token}'
    return req


def validate_repo_names(repos):
    """Tell whether repo names are valid"""
    for r in repos:
        s = r.split('/')
        if (s[0] == r):
            return r
        if (s[0] == '') or (s[1] == ''):
            return r
        if (s[0].find('/') != -1) or (s[1].find('/') != -1):
            return r
    return True


def create_session(config_auth):
    """Create session using the access token"""
    global token
    token = get_auth(config_auth)
    if token == False:
        return False
    session = requests.Session()
    session.headers = {'User-Agent': 'soucevi1'}
    session.auth = token_auth
    return session


def get_repo_prs(r, state, base, session):
    """
    Get all pull requests of a given repository
        r: string 'author/repo-name'
        state: state of the PR
        base: base branch
        session: open and authenticated session
    """
    payload = {'state': state, 'base': base}
    pulls = session.get(f'https://api.github.com/repos/{r}/pulls', params=payload)
    if pulls.status_code != 200:
        return False

    pjlist = pulls.json()
    if 'Link' in pulls.headers:
        while True:
            links = requests.utils.parse_header_links(pulls.headers['Link'])
            n_flag = False
            for l in links:
                if l['rel'] == 'next':
                    pulls = session.get(l['url'])
                    if pulls.status_code != 200:
                        return False
                    n_flag = True
                    break            
            if n_flag == False:
                break 
            pjlist += pulls.json()
    return pjlist


def get_pr_files(r, session, pull_num):
    """
    Get list containing all the files that are modified in the current pull request
        r: string 'author/repo-name'
        session: open and authenticated session
        pull_num: number of the pull request
    """
    pull_files = session.get(f'https://api.github.com/repos/{r}/pulls/{pull_num}/files')
    if pull_files.status_code != 200:
        print(f'Response code: {pull_files.status_code} from https://api.github.com/repos/{r}/pulls/{pull_num}/files', file=sys.stderr)
        return False
    flist = get_pr_filenames(pull_files.json())

    lasturl = 'abc'
    if 'Link' not in pull_files.headers:
        return flist

    while True:
        links = requests.utils.parse_header_links(pull_files.headers['Link'])
        n_flag = False
        for l in links:
            if l['rel'] == 'next':
                pull_files = session.get(l['url'])
                if pull_files.status_code != 200:
                    print(f'Response code: {pull_files.status_code} from https://api.github.com/repos/{r}/pulls/{pull_num}/files', file=sys.stderr)
                    return False
                n_flag = True
                break
        flist += get_pr_filenames(pull_files.json())
        if n_flag == False:
            break        
    return flist


def get_pr_filenames(fj):
    """
    Parse filenames from file json
        fj: files json
    """
    fns = []
    for i in range(len(fj)):
        fns.append(fj[i]['filename'])
    return fns


def get_all_labels(filenames, pattern_dict):
    """
    Get labels to add to the PR
        filenames: list of fns
        paterns: dict "label:[pattern, p...]"
    """
    ret = []
    for fn in filenames:
        for entry in pattern_dict:
            for i in range(len(pattern_dict[entry])):
                if (fnmatch.fnmatch(fn, pattern_dict[entry][i])) and (entry not in ret):
                    ret.append(entry)              
    return ret


def get_label_patterns(file):
    """
    Parse fn patterns from config file
    """
    config = configparser.ConfigParser()
    config.read_file(file)
    if config.has_section('labels') == False:
        return False
    opts = config.options('labels')
    ret = {}
    for o in opts:
        patterns = config.get('labels', o)
        patts = patterns.split('\n')
        if '' in patts:
            patts.remove('')
        ret[o] = patts
    return ret
    


def get_unknown_labels_to_keep(labels_curr, pattern_dict):
    """
    Filter out the labels that match the configuration file
    """
    ret = []
    pat = []
    for entry in pattern_dict:
        pat.append(entry)
    for l in labels_curr:
        if l in pat:
            continue
        else:
            ret.append(l)
    return ret


def add_labels(repo, pull_num, labels, session):
    """
    Add all the labels to the PR
    """
    params = json.dumps(labels)
    ret = session.put(f'https://api.github.com/repos/{repo}/issues/{pull_num}/labels', 
        data=params)
    if ret.status_code != 200:
        return False
    if test_labels_added(repo, pull_num, labels, session) == False:
        return False
    return True


def test_labels_added(repo, pull_num, labels, session):
    """
    Test whether the labels were added correctly (permissions etc.)
    """
    ret = session.get(f'https://api.github.com/repos/{repo}/issues/{pull_num}/labels')
    if ret.status_code != 200:
        return False

    llist = get_label_names(ret.json())

    if 'Link' in ret.headers:
        while True:
            links = requests.utils.parse_header_links(ret.headers['Link'])
            n_flag = False
            for l in links:
                if l['rel'] == 'next':
                    ret = session.get(l['url'])
                    if ret.status_code != 200:
                        return False
                    n_flag = True
                    break
            llist += get_label_names(ret.json())
            if n_flag == False:
                break    
    if set(llist) != set(labels):
        return False
    return True


def get_label_names(l_json):
    """
    Get names of all the labels in given json
    """
    llist = []
    for j in l_json:
        llist.append(j['name'])
    return llist


def get_added_labels(l_new, l_old):
    """
    Get labels that are new to this PR
    """
    ret = []
    for l in l_new:
        if l in l_old:
            continue
        else:
            ret.append(l)
    return ret


def get_current_labels(lj):
    """
    Get labels from json file
    """
    ret = []
    for i in lj:
        ret.append(i['name'])
    return ret


def get_new_in_current(l_new, l_old, pattern_dict):
    """
    Get those labels, that are supposed to be added but 
    were already there and known
    """
    ret = []
    ret2 = []
    for l in l_new:
        if l in l_old:
            ret.append(l)
    for l in ret:
        if l in pattern_dict:
            ret2.append(l)
    return ret2


def get_current_in_all(l_to_add, l_old, pattern_dict):
    """
    Get those labels that were already there and known
    """
    ret = []
    ret2 = []
    for l in l_to_add:
        if l in l_old:
            ret.append(l)
    for l in ret:
        if l in pattern_dict:
            ret2.append(l)
    return ret2


def get_removed(l_new, l_old, fpatterns):
    """
    Get those labels that are supposed to be removed
    """
    ret = []
    ret2 = []
    for l in l_old:
        if l in fpatterns:
            ret.append(l)
    for l in ret:
        if l not in l_new:
            ret2.append(l)
    return ret2



@click.command()
@click.argument('REPOSLUGS', nargs=-1)
@click.option('-s','--state', type=click.Choice(['open', 'closed', 'all']),
    help='Filter pulls by state.  [default: open]', default='open')
@click.option('-d/-D','--delete-old/--no-delete-old', 
    help='Delete labels that do not match anymore. [default: True]', default=True)
@click.option('-b', '--base', metavar='BRANCH', 
    help='Filter pulls by base (PR target) branch name.')
@click.option('-a', '--config-auth', metavar='FILENAME', 
    type=click.File('r'), help='File with authorization configuration.')
@click.option('-l', '--config-labels', metavar='FILENAME', 
    type=click.File('r'), help='File with labels configuration.')

def main(config_auth, config_labels, reposlugs, state, delete_old, base):
    """CLI tool for filename-pattern-based labeling of GitHub PRs"""
    colorama.init(autoreset=True)
    # Validate inputs and parameters
    if config_auth == None:
        print('Auth configuration not supplied!', file=sys.stderr)
        sys.exit(1)
    if config_labels == None:
        print('Labels configuration not supplied!', file=sys.stderr)
        sys.exit(1)
    rep = validate_repo_names(reposlugs)
    if rep != True:
        print(f'Reposlug {rep} not valid!', file=sys.stderr)
        sys.exit(1)

    fpatterns = get_label_patterns(config_labels)
    if fpatterns == False:
        print('Labels configuration not usable!', file=sys.stderr)
        sys.exit(1)

    # Open a session
    session = create_session(config_auth)
    if session == False:
        print('Auth configuration not usable!', file=sys.stderr)
        sys.exit(1)        

    # Iterate through all the repositories
    for r in reposlugs:
        # Get all PRs of the current repo
        pulls_json = get_repo_prs(r, state, base, session)
        if pulls_json == False:
            print(color.BOLD + 'REPO ' + color.END + r + ' - ' + color.RED + color.BOLD + 'FAIL')
            continue
        print(color.BOLD + 'REPO ' + color.END + r + ' - ' + color.GREEN + color.BOLD + 'OK')
        # For each PR find its number, current labels and get info about the files
        for n in range(len(pulls_json)):
            pull_num = pulls_json[n]['number']
            labels_current = get_current_labels(pulls_json[n]['labels'])
            pull_files_json_list = get_pr_files(r, session, pull_num)
            if pull_files_json_list == False:
                print(color.BOLD + '  PR ' + color.END + f'https://github.com/{r}/pull/{pull_num} - ' + color.BOLD + color.RED + 'FAIL')
                continue
            pull_filenames = pull_files_json_list#get_pr_filenames(pull_files_json_list)   
            labels_new = get_all_labels(pull_filenames, fpatterns)              

            labels_to_add = []
            labels_plus = []
            labels_minus = []
            labels_eq = []
            fl = False
            if delete_old == True:
                # Delete old
                u_labels_to_keep = get_unknown_labels_to_keep(labels_current, fpatterns)
                labels_to_add = labels_new#labels_to_keep + labels_new
                labels_to_add += u_labels_to_keep
                labels_to_add = list(set(labels_to_add))
                fl = add_labels(r, pull_num, labels_to_add, session)
                labels_plus = get_added_labels(labels_new, labels_current)
                labels_eq = get_new_in_current(labels_new, labels_current, fpatterns)
                labels_minus = get_removed(labels_new, labels_current, fpatterns)                

            else:
                # No delete old
                labels_to_add = labels_new + labels_current
                labels_to_add = list(set(labels_to_add))
                fl = add_labels(r, pull_num, labels_to_add, session)
                labels_plus = get_added_labels(labels_new, labels_current)
                labels_eq = get_current_in_all(labels_new, labels_current, fpatterns)

            if fl == True:
                labels_to_print = []
                for x in labels_plus:
                    labels_to_print.append(('+', x))
                for x in labels_minus:
                    labels_to_print.append(('-', x))
                for x in labels_eq:
                    labels_to_print.append(('=', x))
                labels_to_print.sort(key=lambda tup: tup[1])
                print(color.BOLD + '  PR ' + color.END + f'https://github.com/{r}/pull/{pull_num} - ' + color.BOLD + color.GREEN + 'OK')
                for l in labels_to_print:
                    if l[0] == '+':
                        print('    ' + color.GREEN + f'+ {l[1]}' + color.END)
                    elif l[0] == '-':
                        print('    ' + color.RED + f'- {l[1]}' + color.END)
                    elif l[0] == '=':
                        print(f'    = {l[1]}')
            else:
                print(color.BOLD + '  PR ' + color.END + f'https://github.com/{r}/pull/{pull_num} - ' + color.BOLD + color.RED + 'FAIL')


if __name__ == '__main__':
    main()