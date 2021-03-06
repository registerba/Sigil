#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab

# Copyright (c) 2020 Kevin B. Hendricks, Stratford Ontario Canada
# All rights reserved.
#
# This file is part of Sigil.
#
#  Sigil is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Sigil is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Sigil.  If not, see <http://www.gnu.org/licenses/>.

import sys
import os
import re
import shutil

import dulwich
from dulwich import porcelain
from dulwich.repo import Repo

import zlib
import zipfile
from zipfile import ZipFile

from contextlib import contextmanager

@contextmanager
def make_temp_directory():
    import tempfile
    import shutil
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)

_SKIP_LIST = [
    'encryption.xml',
    'rights.xml',
    '.gitignore',
    '.gitattributes'
    '.bookinfo'
]

# convert string to utf-8
def utf8_str(p, enc='utf-8'):
    if p is None:
        return None
    if isinstance(p, str):
        return p.encode('utf-8')
    if enc != 'utf-8':
        return p.decode(enc, errors='replace').encode('utf-8')
    return p

# convert string to be unicode encoded
def unicode_str(p, enc='utf-8'):
    if p is None:
        return None
    if isinstance(p, str):
        return p
    return p.decode(enc, errors='replace')

fsencoding = sys.getfilesystemencoding()

# handle paths that might be filesystem encoded
def pathof(s, enc=fsencoding):
    if s is None:
        return None
    if isinstance(s, str):
        return s
    if isinstance(s, bytes):
        try:
            return s.decode(enc)
        except:
            pass
    return s

# properly handle relative paths
def relpath(path, start=None):
    return os.path.relpath(pathof(path) , pathof(start))

# generate a list of files in a folder
def walk_folder(top):
    top = pathof(top)
    rv = []
    for base, dnames, names  in os.walk(top):
        base = pathof(base)
        for name in names:
            name = pathof(name)
            rv.append(relpath(os.path.join(base, name), top))
    return rv


# borrowed from calibre from calibre/src/calibre/__init__.py
# added in removal of non-printing chars
# and removal of . at start
def cleanup_file_name(name):
    import string
    _filename_sanitize = re.compile(r'[\xae\0\\|\?\*<":>\+/]')
    substitute='_'
    one = ''.join(char for char in name if char in string.printable)
    one = _filename_sanitize.sub(substitute, one)
    one = re.sub(r'\s', '_', one).strip()
    one = re.sub(r'^\.+$', '_', one)
    one = one.replace('..', substitute)
    # Windows doesn't like path components that end with a period
    if one.endswith('.'):
        one = one[:-1]+substitute
    # Mac and Unix don't like file names that begin with a full stop
    if len(one) > 0 and one[0:1] == '.':
        one = substitute+one[1:]
    return one

# routine to copy the files internal to Sigil for the epub being edited
# to a destination folder
#   bookroot is path to root folder of epub inside Sigil
#   bookfiles is list of all bookpaths (relative to bookroot) that make up the epub
#   path to the destination folder
def copy_book_contents_to_destination(book_home, filepaths, destdir):
    copied = []
    for apath in filepaths:
        src = os.path.join(book_home, apath)
        dest = os.path.join(destdir, apath)
        # and make sure destination directory exists
        base = os.path.dirname(dest)
        if not os.path.exists(base):
            os.makedirs(base)
        data = b''
        with open(src, 'rb') as f:
            data = f.read()
        with open(dest,'wb') as fp:
            fp.write(data)
        copied.append(apath)
    # Finally Add the proper mimetype file
    data = b"application/epub+zip"
    with open(os.path.join(destdir,"mimetype"),'wb') as fm:
        fm.write(data)
    copied.append("mimetype")
    return copied

def add_gitignore(repo_path):
    ignoredata = []
    ignoredata.append(".DS_Store")
    ignoredata.append("*~")
    ignoredata.append("*.orig")
    ignoredata.append("*.bak")
    ignoredata.append(".bookinfo")
    ignoredata.append(".gitignore")
    ignoredata.append(".gitattributes")
    ignoredata.append("")
    data = "\n".join(ignoredata).encode('utf-8')
    with open(os.path.join(repo_path, ".gitignore"),'wb') as f1:
        f1.write(data)


def add_gitattributes(repo_path):
    adata = []
    adata.append(".git export-ignore")
    adata.append(".gitattributes export-ignore")
    adata.append(".gitignore export-ignore")
    adata.append(".bookinfo export-ignore")
    adata.append("")
    data = "\n".join(adata).encode('utf-8')
    with open(os.path.join(repo_path, ".gitattributes"),'wb') as f3:
        f3.write(data)

def add_bookinfo(repo_path, filename, bookid):
    bookinfo = []
    bookinfo.append(filename)
    bookinfo.append(bookid)
    bookinfo.append("")
    data = "\n".join(bookinfo).encode('utf-8')
    with open(os.path.join(repo_path, ".bookinfo"),'wb') as f2:
        f2.write(data)

# return True if file should be copied to destination folder
def valid_file_to_copy(rpath):
    segs = rpath.split(os.sep)
    if ".git" in segs:
        return False
    filename = os.path.basename(rpath)
    keep = filename not in _SKIP_LIST
    return keep


def build_epub_from_folder_contents(foldpath, epub_filepath):
    outzip = zipfile.ZipFile(pathof(epub_filepath), mode='w')
    files = walk_folder(foldpath)
    if 'mimetype' in files:
        outzip.write(pathof(os.path.join(foldpath, 'mimetype')), pathof('mimetype'), zipfile.ZIP_STORED)
    else:
        raise Exception('mimetype file is missing')
    files.remove('mimetype')
    for file in files:
        if valid_file_to_copy(file):
            filepath = os.path.join(foldpath, file)
            outzip.write(pathof(filepath),pathof(file),zipfile.ZIP_DEFLATED)
    outzip.close()


# the entry points from Cpp

def generate_epub_from_tag(localRepo, bookid, tagname, filename, dest_path):
    repo_home = pathof(localRepo)
    repo_home = repo_home.replace("/", os.sep)
    repo_path = os.path.join(repo_home, "epub_" + bookid)
    cdir = os.getcwd()
    # first verify both repo and tagname exist
    epub_filepath = ""
    epub_name = filename + "_" + tagname + ".epub"
    taglst = []
    if os.path.exists(repo_path):
        os.chdir(repo_path)
        tags = porcelain.list_tags(repo='.')
        for atag in tags:
            taglst.append(unicode_str(atag))
        if tagname not in taglst:
            return epub_file_path
        # make a temporary repo to clone into
        # workaround to the fact that dulwich does not support clean checkouts
        # of branches or tags into existing working directories nor does it support merges
        with make_temp_directory() as scratchrepo:
            # should clone current repo "s" into scratchrepo "r"
            s = Repo(".")
            r = s.clone(scratchrepo, mkdir=False, bare=False, origin=b"origin", checkout=False)
            s.close()
            os.chdir(scratchrepo)
            tagkey = utf8_str("refs/tags/" + tagname)
            r.reset_index(r[tagkey].tree)
            r.refs.set_symbolic_ref(b"HEAD", tagkey)
            r.close()
            os.chdir(cdir)

            # working directory of scratch repo should now be populated
            epub_filepath = os.path.join(dest_path, epub_name)
            try:
                build_epub_from_folder_contents(scratchrepo, epub_filepath)
            except Exception as e:
                print("epub creation failed")
                print(str(e))
                epub_filepath = ""
                pass
        os.chdir(cdir)
    return epub_filepath
        

def get_tag_list(localRepo, bookid):
    repo_home = pathof(localRepo)
    repo_home = repo_home.replace("/", os.sep)
    repo_path = os.path.join(repo_home, "epub_" + bookid)
    cdir = os.getcwd()
    taglst = []
    if os.path.exists(repo_path):
        os.chdir(repo_path)
        # determine the new tag
        tags = porcelain.list_tags(repo='.')
        for atag in tags:
            taglst.append(unicode_str(atag))
        os.chdir(cdir)
    return taglst


def performCommit(localRepo, bookid, filename, bookroot, bookfiles):
    has_error = False
    staged = []
    added=[]
    ignored=[]
    # convert url paths to os specific paths
    repo_home = pathof(localRepo)
    repo_home = repo_home.replace("/", os.sep)
    repo_path = os.path.join(repo_home, "epub_" + bookid)
    book_home = pathof(bookroot)
    book_home = book_home.replace("/", os.sep);
    # convert from bookpaths to os relative file paths
    filepaths = []
    for bkpath in bookfiles:
        afile = pathof(bkpath)
        afile = afile.replace("/", os.sep)
        filepaths.append(afile)

    cdir = os.getcwd()
    if os.path.exists(repo_path):
        # handle updating the staged files and commiting and tagging
        # first collect info to determine files to delete form repo
        # current tag, etc
        os.chdir(repo_path)
        # determine the new tag
        tags = porcelain.list_tags(repo='.')
        tagname = "V%04d" % (len(tags) + 1)
        # delete files that are no longer needed from staging area
        tracked = []
        tracked = porcelain.ls_files(repo='.')
        files_to_delete = []
        for afile in tracked:
            afile = pathof(afile)
            if afile not in filepaths:
                if afile not in  ["mimetype", ".gitignore", ".bookinfo"]:
                    files_to_delete.append(afile)
        if len(files_to_delete) > 0:
            porcelain.rm(repo='.',paths=files_to_delete)
        # copy over current files
        copy_book_contents_to_destination(book_home, filepaths, repo_path)
        (staged, unstaged, untracked) = porcelain.status(repo='.')
        files_to_update = []
        for afile in unstaged:
            afile = pathof(afile)
            files_to_update.append(afile)
        for afile in untracked:
            afile = pathof(afile)
            files_to_update.append(afile)
        (added, ignored) = porcelain.add(repo='.', paths=files_to_update)
        commit_sha1 = porcelain.commit(repo='.',message="updating to " + tagname, author=None, committer=None)
        tag = porcelain.tag_create(repo='.', tag=tagname, message="Tagging..." + tagname, author=None)
        os.chdir(cdir)
    else:
        # this will be an initial commit to this repo
        tagname = 'V0001'
        os.makedirs(repo_path)
        add_gitignore(repo_path)
        add_gitattributes(repo_path)
        cdir = os.getcwd()
        os.chdir(repo_path)
        r = porcelain.init(path='.', bare=False)
        staged = copy_book_contents_to_destination(book_home, filepaths, repo_path)
        (added, ignored) = porcelain.add(repo='.',paths=staged)
        commit_sha1 = porcelain.commit(repo='.',message="Initial Commit", author=None, committer=None)
        tag = porcelain.tag_create(repo='.', tag=tagname, message="Tagging..." + tagname, author=None)
        os.chdir(cdir)
        add_bookinfo(repo_path, filename, bookid)
    result = "\n".join(added);
    result = result + "***********" + "\n".join(ignored)
    if not has_error:
        return result;
    return ''

def eraseRepo(localRepo, bookid):
    repo_home = pathof(localRepo)
    repo_home = repo_home.replace("/", os.sep)
    repo_path = os.path.join(repo_home, "epub_" + bookid)
    success = 1
    cdir = os.getcwd()
    if os.path.exists(repo_path):
        try:
            shutil.rmtree(repo_path)
        except Exception as e:
            print("repo erasure failed")
            print(str(e))
            success = 0
            pass
    return success


def main():
    argv = sys.argv
    return 0

if __name__ == '__main__':
    sys.exit(main())
