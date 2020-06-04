from git import Repo
import os
import shutil
import stat
import json
import stat
from datetime import datetime
import re
from . import config

# Error handler for windows by:
# https://stackoverflow.com/questions/2656322/shutil-rmtree-fails-on-windows-with-access-is-denied
def onerror(func, path, exc_info):
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Usage : ``shutil.rmtree(path, onerror=onerror)``
    """
    try:
        if not os.access(path, os.W_OK):
            # Is the error an access error ?
            os.chmod(path, stat.S_IWUSR)
            func(path)
    except:
        raise

prev_versions_path = "versions"
prev_versions_deploy_folder = os.path.join(config.web_directory, prev_versions_path)
# allowed characters inside of hyperlinks
allowed_in_link = "".join(list(map(lambda s: s.strip(), [
    "   -   ", 
    "   ?   ",
    "   \w   ",
    "   \\   ",
    "   $   ",
    "   \.   ",
    "   !   ",
    "   \*   ",
    "   '   ",
    "   ()   ",
    "   /    ",
])))

def nameToPath(name):
    # translate a version name to a path, e.g v6.3 => v6
    return name.split(".")[0]

def deploy():
    """ Deploy previous versions to website directory """
    
    #TODO we probably don't need to re-clone the website here, just a git pull should be sufficient
    # delete previous copy of attack-versions
    if os.path.exists(config.versions_directory):
        shutil.rmtree(config.versions_directory, onerror=onerror) 
    # download new version of attack-website for use in versioning
    versions_repo = Repo.clone_from(config.versions_repo, config.versions_directory)

    # remove previously deployed previous versions
    if os.path.exists(prev_versions_deploy_folder):
        for child in os.listdir(prev_versions_deploy_folder):
            if os.path.isdir(os.path.join(prev_versions_deploy_folder, child)): 
                shutil.rmtree(prev_versions_deploy_folder)

    with open("data/versions.json", "r") as f:
        versions = json.load(f)

    # build previous versions
    for version in versions["previous"]:
        deploy_previous_version(version, versions_repo)

    # build the versions page
    build_markdown(versions)
    
    # write robots.txt to disallow crawlers
    with open(os.path.join(config.web_directory, "robots.txt"), "w", encoding='utf8') as robots:
        robots.write(f"User-agent: *\nDisallow: /{config.subdirectory}/previous/\nDisallow:/{config.subdirectory}/{prev_versions_path}/")

def deploy_current_version():
    """build a permalink of the current version"""

    with open("data/versions.json", "r") as f:
        version = json.load(f)["current"]

    os.mkdir(os.path.join(prev_versions_deploy_folder, nameToPath(version["name"])))
    for item in os.listdir("output"):
        # skip previous and versions directories when copying
        if item == "previous" or item == "versions": continue
        # copy the current version into a preserved version
        src = os.path.join("output", item)
        dest = os.path.join(prev_versions_deploy_folder, nameToPath(version["name"]), item)
        # copy depending on file type
        if os.path.isdir(src):
            shutil.copytree(src, dest)
        else: # is file
            shutil.copy(src, dest)

    # run archival scripts
    archive(version, is_current=True)


def deploy_previous_version(version, repo):
    """build a version of the site to /prev_versions_path. version is a version from versions.json, repo is a reference to the attack-website Repo object"""
    # check out the commit for that version
    repo.git.checkout(version["commit"])
    # copy over files
    shutil.copytree(os.path.join(config.versions_directory), os.path.join(prev_versions_deploy_folder, nameToPath(version["name"])))
    # run archival scripts on version
    archive(version)
    # build alias for version
    for alias in version["aliases"]:
        build_alias(nameToPath(version["name"]), alias)

def archive(version_data, is_current=False):
    """perform archival operations on a version in /prev_versions_path
    - remove unnecessary files (.git, CNAME, preserved versions for that version)
    - replace links on all pages
    - add archived version banner to all pages
    """
    version = nameToPath(version_data["name"])

    version_path = os.path.join(prev_versions_deploy_folder, version) # root of the filesystem containing the version
    version_url_path = os.path.join(prev_versions_path, version) # root of the URL of the version, for prefixing URLs

    def saferemove(path, type):
        if not os.path.exists(path): return
        if type == "file":
            os.remove(path)
        elif type == "directory":
            shutil.rmtree(path, onerror=onerror)

    # remove .git
    saferemove(os.path.join(version_path, ".git"), "directory")
    # remove CNAME
    saferemove(os.path.join(version_path, "CNAME"), "file")
    # remove robots
    saferemove(os.path.join(version_path, "robots.txt"), "file")

    # remove previous versions from this previous version
    for prev_directory in map(lambda d: os.path.join(version_path, d), ["previous", prev_versions_path, os.path.join("resources", "previous-versions"), os.path.join("resources", "versions")]):
        if os.path.exists(prev_directory):
            shutil.rmtree(prev_directory, onerror=onerror)
    
    # remove updates page
    updates_dir = os.path.join(version_path, "resources", "updates")
    if os.path.exists(updates_dir):
        shutil.rmtree(updates_dir, onerror=onerror)

    # walk version HTML files
    for directory, _, files in os.walk(version_path):
        for filename in filter(lambda f: f.endswith(".html"), files):
            # replace links in the file

            # open the file
            filepath = os.path.join(directory, filename)
            with open(filepath, mode="r", encoding="utf8") as html:
                html_str = html.read()

            # helper function to substitute links so that they point to /versions/
            dest_link_format = f"/{version_url_path}\g<1>"
            def substitute(prefix, html_str):
                fromstr = f"{prefix}=[\"'](?!\/versions\/)([{allowed_in_link}]+)[\"']"
                tostr = f'{prefix}="{dest_link_format}"'
                return re.sub(fromstr, tostr, html_str)
            # ditto, but for redirections
            def substitute_redirection(prefix, html_str):
                from_str = f"{prefix}=([{allowed_in_link}]+)[\"']"
                to_str = f'{prefix}={dest_link_format}"'
                return re.sub(from_str, to_str, html_str)
            
            # replace links so that they properly point to where the version is stored
            html_str = substitute("src", html_str)
            html_str = substitute("href", html_str)
            html_str = substitute_redirection('content="0; url', html_str)
            # update links to previous-versions to point to the main site instead of an archived page
            for previous_page in ["previous-versions", "versions"]: # backwards compatability
                html_str = html_str.replace(f"/{version_url_path}/resources/{previous_page}/", "/resources/versions/")
            # update links to updates to point to main site instead of archied page
            html_str = html_str.replace(f"/{version_url_path}/resources/updates/", "/resources/updates/")
            
            # update versioning button to show the permalink site version, aka "back to main site"
            html_str = html_str.replace("version-button live", "version-button permalink")
            # update live version links on the versioning button
            from_str = f"href=[\"']\/versions\/v\d+([{allowed_in_link}]+[\"']>live version<\/a>)"
            to_str = f'href="\g<1>'
            html_str = re.sub(from_str, to_str, html_str)

            # remove banner message if it is present
            for banner_class in ["banner-message", "under-development"]: # backwards compatability
                html_str = html_str.replace(banner_class, "d-none") # hide the banner

            # format banner depending on if this is the current version or a previous version
            if is_current: version_marking = f'Currently viewing <a href="{version_data["cti_url"]}" target="_blank">ATT&CK {version_data["name"]}</a> which is the current version of ATT&CK.'
            else: version_marking = f'Currently viewing <a href="{version_data["cti_url"]}" target="_blank">ATT&CK {version_data["name"]}</a> which was live between {version_data["date_start"]} and {version_data["date_end"]}.'

            # add versions banner
            for banner_tag in ["<!-- !previous versions banner! -->", "<!-- !versions banner! -->"]: # backwards compatability
                html_str = html_str.replace(banner_tag, (\
                        '<div class="container-fluid version-banner">'\
                        f'<div class="icon-inline baseline mr-1"><img src="/{version_url_path}/theme/images/icon-warning-24px.svg"></div>'\
                        f'{version_marking} '\
                        '<a href="/resources/versions/">Learn more about the versioning system</a> or <a href="/">see the live site</a>.</div>'
                ))

            # overwrite with updated html
            with open(filepath, mode="w", encoding='utf8') as updated_html:
                updated_html.write(html_str)

    # update search page
    for search_file_name in ["search.js", "search_babelized.js"]:
        search_file_path = os.path.join(version_path, "theme", "scripts", search_file_name)
        if os.path.exists(search_file_path):

            with open(search_file_path, mode="r", encoding='utf8') as search_file:
                search_contents = search_file.read()

            search_contents = re.sub('site_base_url ?= ? ""', f'site_base_url = "/{version_url_path}"', search_contents)

            with open(search_file_path, mode="w", encoding='utf8') as search_file:
                search_file.write(search_contents)

def build_alias(version, alias):
    """build redirects from alias to version
    version is the path of the version, e.g "v5"
    alias is the alias to build, e.g "october2018"
    """
    for root, folder, files in os.walk(os.path.join(prev_versions_deploy_folder, version)):
        for thefile in files:
            # where the file should go
            newRoot = root.replace(version, alias).replace(prev_versions_path, "previous")
            # file to build
            redirectFrom = os.path.join(newRoot, thefile)
            
            # where this file should point to
            if thefile == "index.html": 
                redirectTo = root # index.html is implicit
            else:
                redirectTo = "/".join([root, thefile])  # file is not index.html so it needs to be specified explicitly
            redirectTo = redirectTo.split("output")[1] # remove output folder from path

            # write the redirect file
            if not os.path.isdir(newRoot):
                os.makedirs(newRoot, exist_ok=True) # make parents as well
            with open(redirectFrom, "w") as f:
                f.write(f'<meta http-equiv="refresh" content="0; url={redirectTo}"/>')

def build_markdown(versions):
    """build markdown for the versions list page"""
    # build urls
    versions["current"]["url"] = nameToPath(versions["current"]["name"])
    versions["current"]["changelog_label"] = " ".join(versions["current"]["changelog"].split("-")[1:]).title()

    for versionGroup in ["previous", "older"]: # apply transforms to both previous and older
        for version in versions[versionGroup]:
            version["url"] = nameToPath(version["name"])
            version["changelog_label"] = " ".join(version["changelog"].split("-")[1:]).title()

    # sort previous versions by date
    versions_data = {
        "current": versions["current"], 
        "previous": sorted(versions["previous"], key=lambda p: datetime.strptime(p["date_end"], "%B %d, %Y"), reverse=True),
        "older": sorted(versions["older"], key=lambda p: datetime.strptime(p["date_end"], "%B %d, %Y"), reverse=True)
    }
    
    # build previous-versions page markdown
    subs = config.versions_md + json.dumps(versions_data)
    with open(os.path.join(config.versions_markdown_path, "versions.md"), "w", encoding='utf8') as md_file:
        md_file.write(subs)


