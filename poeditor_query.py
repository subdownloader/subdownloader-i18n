#!/usr/bin/env python3

import argparse
import ast
import datetime
import logging
import os
try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib
from subprocess import check_call
import sys

file_path = pathlib.Path(os.path.dirname(os.path.realpath(__file__)))

sys.path.append(str(file_path / "submodules" / "python-poeditor"))
import poeditor

log = logging.getLogger("query")
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)


class Mapping:
    def __init__(self):
        self._local = None
        self._server = None
        self._name = None
        self._server_completed = None
        self._server_updated = None

    @classmethod
    def create_local(cls, local):
        mapping = cls()
        mapping.set_local(local)
        return mapping

    def set_local(self, local):
        self._local = local

    @classmethod
    def create_server(cls, server, name):
        mapping = cls()
        mapping.set_server(server=server, name=name)
        return mapping

    def set_server(self, server, name, server_completed=None, server_updated=None):
        self._server = server
        self._name = name
        self._server_completed = server_completed
        self._server_updated = server_updated

    def matches_code(self, code):
        if self.local():
            if self.local().lower() == code.replace("-", "_").lower():
                return True
        if self.server():
            if self.server().lower() == code.replace("_", "-").lower():
                return True
        return False

    def local(self):
        return self._local

    def _local_to_server(self, fixes):
        for local, server in fixes.items():
            if local == self.local() or server == self.local():
                return server
        return self.local().replace("_", "-").lower()

    def server(self):
        return self._server

    def _server_to_local(self, fixes):
        for local, server in fixes.items():
            if local == self.server() or server == self.server():
                return local
        parts = self.server().split("-")
        parts = parts[:1] + [part.upper() for part in parts[1:]]
        return "_".join(parts)

    def name(self):
        return self._name

    def progress(self):
        return self._server_completed

    def updated(self):
        return self._server_updated

    def sync_from_server(self, api, project_id, project_name, root_path, fixes):
        log.debug("Mapping.sync_from_server(server={server}) ...".format(server=self.server()))
        if not self.server():
            log.error("Cannot sync from server if language is not on server")
            return False
        log.debug("Fetching translations from server ...")
        server_po_url, server_po_file = api.export(project_id=project_id, language_code=self.server(),
                                          file_type="po")
        log.debug("... Translations fetched!")

        local = self._server_to_local(fixes=fixes)
        local_po_path = (root_path / local / project_name).with_suffix(".po")
        log.debug("Local po path:{local_po}".format(local_po=str(local_po_path)))

        if not local_po_path.exists():
            log.debug("Language {server} was not local yet.".format(server=self.server()))
            log.debug("Moving downloaded po file to local.")
            local_po_path.parent.mkdir(exist_ok=True)
            pathlib.Path(server_po_file).rename(local_po_path)
            self.set_local(local=local)
        else:
            log.debug("Language {server} is already local.".format(server=self.server()))
            log.debug("Merging downloaded translations into local translations ...")
            # check_call(["msgmerge", "--previous", "-U", str(local_po_path), server_po_file])
            check_call(["msgcat", server_po_file, str(local_po_path), "-o", str(local_po_path)])
            log.debug("... merging done!")
        return True

    def _server_to_name(self, api, server):
        try:
            available_languages = api.available_languages()
            server_language = next(name_server for name_server in available_languages.items() if name_server[1] == server)
            return server_language[0]
        except StopIteration:
            raise KeyError("Server does not know about language {server}".format(server=server))

    def sync_to_server(self, api, project_id, project_name, root_path, fixes):
        log.debug("Mapping.sync_to_server(local={local}) ...".format(local=self.local()))
        if not self.local():
            raise ValueError("Cannot sync to server if language is not local")
        local_po_path = (root_path / self.local() / project_name).with_suffix(".po")
        log.debug("Local po path:{local_po}".format(local_po=str(local_po_path)))
        if not self.server():
            log.debug("Language {local} is not on the server yet.".format(local=self.local()))
            server = self._local_to_server(fixes=fixes)
            log.debug("Creating {server} on server ...".format(server=server))
            try:
                api.add_language_to_project(project_id=project_id, language_code=server)
            except poeditor.POEditorException:
                log.error("server AND fixes does not know about language {server}".format(server=server))
                return False
            log.debug("... Language {server} created created on server".format(server=server))
            try:
                name = self._server_to_name(api, server)
            except KeyError:
                log.warning("server does not know about language {server}".format(server=server))
                return False
            self.set_server(server=server, name=name)

        log.debug("Uploading translation {server} to server ...".format(server=self.server()))
        api.update_terms_definitions(project_id=project_id, language_code=self.server(), file_path=str(local_po_path),
                                     overwrite=True, sync_terms=True)
        log.debug("... Upload finished")
        return True

    def delete_on_server(self, api, project_id):
        log.debug("Mapping.delete_on_server({server})".format(server=self.server()))
        if self.server():
            log.debug("Sending delete request ...")
            api.delete_language_from_project(project_id=project_id, language_code=self.server())
            log.debug("... delete done!")
            self.set_server(server=None, name=None)
            return True
        return False

    FORMAT_STR = "{local:>8} {local_avail:>1} {server_avail:>1} {server:7} {name:21} {completed:>5} {updated}"

    def table_str(self):
        local = self.local() if self.local() else ""
        server = self.server() if self.server() else ""
        local_avail = "x" if local else " "
        server_avail = "x" if server else " "
        name = self.name() if self.name() else ""
        completed = "{:>3.1f}".format(self._server_completed if self._server_completed else 0)
        updated = datetime.datetime.strftime(self._server_updated, "%Y-%m-%d %H:%M:%S") if self._server_updated else ""
        return self.FORMAT_STR.format(local=local, local_avail=local_avail,
                                      server_avail=server_avail, server=server,
                                      name=name, completed=completed, updated=updated)

    @classmethod
    def table_header(cls):
        return cls.FORMAT_STR.format(local="local", local_avail="L",
                                     server_avail="S", server="server",
                                     name="name", completed="%", updated="updated")


class Mappings:
    def __init__(self, project_name, project_id, language_root_path, fixes):
        self._mappings = []
        self._project_name = project_name
        self._project_id = project_id
        self._language_root_path = language_root_path
        self._fixes = fixes

    @classmethod
    def from_project_name(cls, api, project_name, language_root_path, fixes):
        project_id = project_name_to_id(api, project_name)
        if project_id is None:
            log.error("Server does not have project {project_name}".format(project_name=project_name))
            raise KeyError("Illegal project name {project_name}".format(project_name=project_name))

        local_languages_paths = [f for f in language_root_path .iterdir() if f.is_dir()]

        mappings = cls(project_name=project_name, project_id=project_id,
                       language_root_path=language_root_path, fixes=fixes)
        for local_language_path in local_languages_paths:
            mappings.add_mapping(Mapping.create_local(local=local_language_path.name))

        server_languages = api.list_project_languages(project_id=project_id)

        for server in server_languages:
            try:
                mapping = mappings.get_mapping(server["code"])
                mapping.set_server(server=server["code"], name=server["name"],
                                   server_completed=server["percentage"], server_updated=server["updated"])
            except KeyError:
                mapping = Mapping.create_server(server=server["code"], name=server["name"])
                mappings.add_mapping(mapping)
        return mappings

    def get_mapping(self, code):
        def find_mapping(c):
            for mapping in self._mappings:
                if mapping.matches_code(c):
                    return mapping
            return None

        mapping = find_mapping(code)
        if mapping:
            return mapping

        code = code.lower()
        for key, value in self._fixes.items():
            if key.lower() == code or value.lower() == code:
                mapping = find_mapping(key)
                if mapping:
                    return mapping
        raise KeyError("code unknown")

    def add_mapping(self, mapping):
        self._mappings.append(mapping)

    def iter(self, language_filter=None, sort_specs=None):
        if language_filter:
            result = []
            for mapping in self._mappings:
                for f in language_filter:
                    if mapping.matches_code(f):
                        result.append(mapping)
                        break
        else:
            result = list(self._mappings)

        # sort_order None or one of ["l", "s", "n", "p", "t"]
        if "l" in sort_specs:
            result.sort(key=lambda m : m.local() if m.local() else "")
        elif "s" in sort_specs:
            result.sort(key=lambda m : m.server() if m.server() else "")
        elif "n" in sort_specs:
            result.sort(key=lambda m : m.name() if m.name() else "")
        elif "p" in sort_specs:
            result.sort(key=lambda m : m.progress() if m.progress() else 0.0)
        elif "t" in sort_specs:
            result.sort(key=lambda m : m.updated() if m.updated() else datetime.datetime.fromtimestamp(0))

        if "r" in sort_specs:
            result.reverse()

        return result

    def print_table(self, language_filter, sort_specs):
        result_list = [Mapping.table_header()]
        nb_requested = 0
        fails = []
        for mapping in self.iter(language_filter=language_filter, sort_specs=sort_specs):
            nb_requested += 1
            result_list.append(mapping.table_str())
        print("\n".join(result_list))
        return nb_requested, fails

    def sync_from_server(self, api, language_filter, sort_specs):
        nb_requested = 0
        fails = []
        for mapping in self.iter(language_filter=language_filter, sort_specs=sort_specs):
            nb_requested += 1
            result = mapping.sync_from_server(api=api, project_id=self._project_id, project_name=self._project_name,
                                     root_path=self._language_root_path, fixes=self._fixes)
            if not result:
                fails.append(mapping)
        return  nb_requested, fails

    def sync_to_server(self, api, language_filter, sort_specs):
        nb_requested = 0
        fails = []
        for mapping in self.iter(language_filter=language_filter, sort_specs=sort_specs):
            nb_requested += 1
            result = mapping.sync_to_server(api=api, project_id=self._project_id, project_name=self._project_name,
                                     root_path=self._language_root_path, fixes=self._fixes)
            if not result:
                fails.append(mapping)
        return nb_requested, fails

    def delete_on_server(self, api, language_filter, sort_specs):
        print("Are you sure you want to delete languages from the server?")
        name = input("Enter the name of the project to confirm: ")
        if name.lower() != self._project_name:
            print("Wrong name. Canceling")
            return
        nb_requested = 0
        fails = []
        for mapping in self.iter(language_filter=language_filter, sort_specs=sort_specs):
            nb_requested += 1
            result = mapping.delete_on_server(api=api, project_id=self._project_id)
            if not result:
                fails.append(mapping)
        return nb_requested, fails


def project_name_to_id(api, project_name):
    projects = api.list_projects()
    try:
        project = next(p for p in projects if p["name"].lower() == project_name)
    except StopIteration:
        log.error("Server does not have project {project_name}".format(project_name=project_name))
        return None
    return project["id"]


def format_fails(fails):
    return ",".join([fail.local() or fail.server() for fail in fails])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", dest="api_token", default=None, required=False, help="poeditor.com api token")
    parser.add_argument("--name", dest="project_name", default=None, required=False, help="project name")
    parser.add_argument("--fixed", dest="poeditor_fixes", default=None, required=False, help="extra fixes")
    parser.add_argument("--languages", dest="language_filter", nargs="*", default=None, help="language filter")
    parser.add_argument("--sort", "-s", dest="sort_order", default=None, choices=["l", "s", "n", "p", "t"], help="sort order")
    parser.add_argument("--reverse", "-r", dest="reverse_order", action="store_true", help="reverse order")

    download_upload = parser.add_mutually_exclusive_group(required=True)
    download_upload.add_argument("--upload", dest="upload", action="store_true", help="upload translations to poeditor.com")
    download_upload.add_argument("--download", dest="download", action="store_true", help="download translations from poeditor.com")
    download_upload.add_argument("--delete", dest="delete", action="store_true", help="delete translations from poeditor.com")
    download_upload.add_argument("--status", dest="status", action="store_true", help="print status")

    args = parser.parse_args()

    if args.api_token:
        api_token = args.api_token
    else:
        api_token = open(str(file_path / ".poeditor_apitoken")).read().strip()

    if args.project_name:
        project_name = args.project_name.lower()
    else:
        project_name = "subdownloader"

    if args.poeditor_fixes:
        path_poeditor_fixes = args.poeditor_fixes
    else:
        path_poeditor_fixes = str(file_path / "poeditor_fixes")
    poeditor_fixes = ast.literal_eval(open(path_poeditor_fixes).read())

    language_filter = args.language_filter

    sort_specs = ("r" if args.reverse_order else "") + (args.sort_order if args.sort_order else "")

    language_root_path = file_path / project_name
    local_languages_paths = [f for f in language_root_path .iterdir() if f.is_dir()]

    poeditor_api = poeditor.POEditorAPI(api_token=api_token, block_upload=True)

    mappings = Mappings.from_project_name(api=poeditor_api, project_name=project_name,
                                          language_root_path=language_root_path, fixes=poeditor_fixes)

    if args.status:
        nb_requested, fails = mappings.print_table(language_filter=language_filter, sort_specs=sort_specs)

    elif args.download:
        nb_requested, fails = mappings.sync_from_server(api=poeditor_api, language_filter=language_filter,
                                                        sort_specs=sort_specs)

    elif args.upload:
        nb_requested, fails = mappings.sync_to_server(api=poeditor_api, language_filter=language_filter,
                                                      sort_specs=sort_specs)

    elif args.delete:
        nb_requested, fails = mappings.delete_on_server(api=poeditor_api, language_filter=language_filter,
                                                        sort_specs=sort_specs)

    else:
        parser.error("Need command")

    print("Number of languages: {nb_requested}".format(nb_requested=nb_requested))
    if fails:
        print("Failed languages: {fail_str}".format(fail_str=format_fails(fails)))
    print("Done")
