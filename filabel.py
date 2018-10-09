import click
import colorama
import configparser
import requests
import sys
import json
import pprint
import fnmatch

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
    ret = config.get('github', 'token', fallback='Auth configuration not usable!')
    return ret #config['github']['token']


def token_auth(req):
    """Helper function for the session"""
    req.headers['Authorization'] = f'token {token}'
    return req


def validate_repo_names(repos):
    """Tell whether repo names are valid"""
    #print('Validating repo names:')
    for r in repos:
        s = r.split('/')
        if (s[0] == r):
            #print(f'  Not valid: {r}.')
            return r
        if (s[0] == '') or (s[1] == ''):
            #print(f'  Not valid: {r}.')
            return r
        if (s[0].find('/') != -1) or (s[1].find('/') != -1):
            #print(f'  Not valid: {r}.')
            return r
        #print(f'  {r}: OK')
    return True


def create_session(config_auth):
    """Create session using the access token"""
    #print('Creating GitHub session.')
    global token
    token = get_auth(config_auth)
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
    #print(f'Getting PRs of {r}')
    payload = {'state': state, 'base': base}
    pulls = session.get(f'https://api.github.com/repos/{r}/pulls', params=payload)
    if pulls.status_code != 200:
        return False
    return pulls.json()

def get_pr_files(r, session, pull_num):
    """
    Get json containing all the files that are modified in the current pull request
        r: string 'author/repo-name'
        session: open and authenticated session
        pull_num: number of the pull request
    """
    #print(f'Getting file json of {r}: PR {pull_num}')
    pull_files = session.get(f'https://api.github.com/repos/{r}/pulls/{pull_num}/files')
    if pull_files.status_code != 200:
        return False
    #pprint.pprint(pull_files.text)
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
    #print('Parsing filenames from the json file')
    fns = []
    #pprint.pprint(fj)
    for i in range(len(fj)):
        fns.append(fj[i]['filename'])
        #print(f"  filename: {fj[i]['filename']}")        
    #print(fns)
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
    #print(ret)
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
    params = json.dumps(labels)
    ret = session.put(f'https://api.github.com/repos/{repo}/issues/{pull_num}/labels', 
        data=params)
    if ret.status_code != 200:
        #print(ret.status_code)
        #print(ret.json())
        return False
    return True


def remove_labels(repo, pull_num, labels, session):
    params = json.dumps(labels)
    ret = 0
    for l in labels:
        ret = session.delete(f'https://api.github.com/repos/{repo}/issues/{pull_num}/labels/{l}')
        if ret.status_code != 200:
            #print(ret.status_code)
            #print(ret.json())
            return False
    return True


def get_added_labels(l_new, l_old):
    ret = []
    for l in l_new:
        if l in l_old:
            continue
        else:
            ret.append(l)
    return ret


def get_removed_labels(l_new, l_old):
    ret = []
    for l in l_old:
        if l in l_new:
            continue
        else:
            ret.append(l)
    return ret


def get_labels_kept(l_new, l_old, pattern_dict):
    ret = []
    for l in l_new:
        if l in l_old:
            ret.append(l)

    return ret


def get_current_labels(lj):
    ret = []
    for i in lj:
        ret.append(i['name'])
    return ret


def get_new_in_current(l_new, l_old, pattern_dict):
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
    ret = []
    ret2 = []
    #zname co nejsou na aktualnim seznamu
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
    #colorama.init(autoreset=True)
    # Validate inputs and parameters
    if config_auth == None:
        print('Auth configuration not supplied!', file=sys.stderr)
        sys.exit(1)
    if config_labels == None:
        print('Labels configuration not supplied!', file=sys.stderr)
        sys.exit(1)
    rep = validate_repo_names(reposlugs)
    if rep != True:
        print(f'Reposlug {rep} not valid', file=sys.stderr)
        sys.exit(1)

    fpatterns = get_label_patterns(config_labels)
    if fpatterns == False:
        print('Labels configuration not usable!', file=sys.stderr)
        sys.exit(1)

    # Open a session
    session = create_session(config_auth)

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
            labels_to_remove = []
            labels_removed = []
            labels_plus = []
            labels_minus = []
            labels_eq = []
            fl = False
            if delete_old == True:
                # smazat stare - naleznu nezname a k nim pridam nove
                u_labels_to_keep = get_unknown_labels_to_keep(labels_current, fpatterns)
                #print(f'to keep {labels_to_keep}')
                labels_to_add = labels_new#labels_to_keep + labels_new
                #print(f'to add {labels_to_add}')
                #labels_to_remove = get_removed_labels(labels_new, labels_current)
                #print(f'to remove {labels_to_remove}')
                labels_to_add += u_labels_to_keep
                labels_to_add = list(set(labels_to_add))
                fl = add_labels(r, pull_num, labels_to_add, session)
                labels_plus = get_added_labels(labels_new, labels_current)
                labels_eq = get_new_in_current(labels_new, labels_current, fpatterns)
                labels_minus = get_removed(labels_new, labels_current, fpatterns)
                if fl == False:
                    break
                #fl = remove_labels(r, pull_num, labels_to_remove, session)

            else:
                # nemazat stare - pouze vezmu stavajici a pridam k nim nove
                labels_to_add = labels_new + labels_current
                labels_to_add = list(set(labels_to_add))
                fl = add_labels(r, pull_num, labels_to_add, session)
                labels_plus = get_added_labels(labels_new, labels_current)
                labels_eq = get_current_in_all(labels_to_add, labels_current, fpatterns)

            if fl == True:
                print(color.BOLD + '  PR ' + color.END + f'https://github.com/{r}/pull/{pull_num} - ' + color.BOLD + color.GREEN + 'OK')
                for l in labels_plus:
                    print('    ' + color.GREEN + f'+ {l}' + color.END)
                for l in labels_minus:
                    print('    ' + color.RED + f'- {l}' + color.END)
                for l in labels_eq:
                    print(f'    = {l}')
            else:
                print(color.BOLD + '  PR ' + color.END + f'https://github.com/{r}/pull/{pull_num} - ' + color.BOLD + color.RED + 'FAIL')




            # TODO: 
            #       - foreign repo - po pridani stitku testovat, jestli se fakt pridaly
            #       - nine_labels - vypisuju neznamy existujici stitek zacinajici na 'a'           
            #           se zaplym delete old            
            #       - GET na PRs je taky strankovany
            #       - closed_prs_no_labels - ??????
            #       - closed_ps_get_labels - nejspis stejne jako vyse
            #           prs se nejspis neberou v potaz (state closed)
            #       - state all nefunguje, pravdepodobne zase zavrene
            #       - master i custom base taky nejspi spatne predavane
            #       - diffs - prebyva = u vypisu
            #       - nevypisuje, kdyz neni zadany konfigurak
            #       - neresi prazdny auth conf
            #       - ZEPTAT se na timeout u setupu



            # SOLVED?:
            #       - labels_empty - u prazdneho konfiguraku stejne vypisuju stavajici (=) stitky
            #           S = VYPISOVAT JENOM ZNAME



# delete old:
#   pridat stitky:
#       stavajici nezname
#       nove zjistene (z nich ale muzou nektere byt stavajici)
#   zjistit:
#       uplne nove (+)
#       nove zjistene, ale stavajici (=)
#       zname, ktere nejsou na aktualnim seznamu (-)
#
# no-delete-old:
#   pridat stitky;
#       vsechny stavajici
#       nove zjistene
#   zjistit:
#       uplne nove (+)
#       zname, ktere uz tam ale byly (=)
#       zde minus neni



if __name__ == '__main__':
    main()