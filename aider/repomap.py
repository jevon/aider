import json
import os
import subprocess
import sys
import tempfile

import tiktoken

from aider import prompts

# Global cache for tags
TAGS_CACHE = {}

# from aider.dump import dump


def to_tree(tags):
    tags = sorted(tags)

    output = ""
    last = [None] * len(tags[0])
    tab = "\t"
    for tag in tags:
        tag = list(tag)

        for i in range(len(last)):
            if last[i] != tag[i]:
                break

        num_common = i
        indent = tab * num_common
        rest = tag[num_common:]
        for item in rest:
            output += indent + item + "\n"
            indent += tab
        last = tag

    return output


def fname_to_components(fname, with_colon):
    path_components = fname.split(os.sep)
    res = [pc + os.sep for pc in path_components[:-1]]
    if with_colon:
        res.append(path_components[-1] + ":")
    else:
        res.append(path_components[-1])
    return res


class RepoMap:
    ctags_cmd = ["ctags", "--fields=+S", "--extras=-F", "--output-format=json"]

    def __init__(self, use_ctags=None, root=None, main_model="gpt-4"):
        if not root:
            root = os.getcwd()
        self.root = root

        if use_ctags is None:
            self.use_ctags = self.check_for_ctags()
        else:
            self.use_ctags = use_ctags

        self.tokenizer = tiktoken.encoding_for_model(main_model)

    def get_repo_map(self, chat_files, other_files):
        res = self.choose_files_listing(other_files)
        if not res:
            return

        files_listing, ctags_msg = res

        if chat_files:
            other = "other "
        else:
            other = ""

        repo_content = prompts.repo_content_prefix.format(
            other=other,
            ctags_msg=ctags_msg,
        )
        repo_content += files_listing

        return repo_content

    def choose_files_listing(self, other_files):
        # 1/4 of gpt-4's context window
        max_map_tokens = 2048

        if not other_files:
            return

        if self.use_ctags:
            files_listing = self.get_tags_map(other_files)
            if self.token_count(files_listing) < max_map_tokens:
                ctags_msg = " with selected ctags info"
                return files_listing, ctags_msg

        files_listing = self.get_simple_files_map(other_files)
        ctags_msg = ""
        if self.token_count(files_listing) < max_map_tokens:
            return files_listing, ctags_msg

    def get_simple_files_map(self, other_files):
        fnames = []
        for fname in other_files:
            fname = self.get_rel_fname(fname)
            fname = fname_to_components(fname, False)
            fnames.append(fname)

        return to_tree(fnames)

    def token_count(self, string):
        return len(self.tokenizer.encode(string))

    def get_rel_fname(self, fname):
        return os.path.relpath(fname, self.root)

    def get_tags_map(self, filenames):
        tags = []
        for filename in filenames:
            if filename.endswith(".md") or filename.endswith(".json"):
                tags.append(self.split_path(filename))
                continue
            tags += self.get_tags(filename)
        if not tags:
            return

        return to_tree(tags)

    def split_path(self, path):
        path = os.path.relpath(path, self.root)
        return [path + ":"]

    def get_tags(self, filename):
        # Check if the file is in the cache and if the modification time has not changed
        file_mtime = os.path.getmtime(filename)
        cache_key = filename
        if cache_key in TAGS_CACHE and TAGS_CACHE[cache_key]["mtime"] == file_mtime:
            return TAGS_CACHE[cache_key]["tags"]

        cmd = self.ctags_cmd + [filename]
        output = subprocess.check_output(cmd).decode("utf-8")
        output = output.splitlines()

        tags = []
        if not output:
            tags.append(self.split_path(filename))

        for line in output:
            tag = json.loads(line)
            path = tag.get("path")
            scope = tag.get("scope")
            kind = tag.get("kind")
            name = tag.get("name")
            signature = tag.get("signature")

            last = name
            if signature:
                last += " " + signature

            res = self.split_path(path)
            if scope:
                res.append(scope)
            res += [kind, last]
            tags.append(res)

        # Update the cache
        TAGS_CACHE[cache_key] = {"mtime": file_mtime, "tags": tags}
        return tags

    def check_for_ctags(self):
        try:
            with tempfile.TemporaryDirectory() as tempdir:
                hello_py = os.path.join(tempdir, "hello.py")
                with open(hello_py, "w") as f:
                    f.write("def hello():\n    print('Hello, world!')\n")
                self.get_tags(hello_py)
        except Exception:
            return False
        return True


if __name__ == "__main__":
    rm = RepoMap()
    res = rm.get_tags_map(sys.argv[1:])
    print(res)
