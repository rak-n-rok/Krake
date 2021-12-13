# Introduction

First off all, thank you for considering contributing to Krake!

There are many ways to contribute, such as improving the documentation,
submitting bug reports and feature requests or writing code which can be
incorporated into Krake itself.

Please, don't use the issue tracker for support questions. Connect with us on
the [Krake Matrix room][krake-matrix] if you  have any questions or need
support.


# How to report a bug

If you find a security vulnerability, do NOT open an issue. Get in touch with
`mgoerens` on the [Krake Matrix room][krake-matrix].

For any other type of bug, please create a issue using the "Issue" template.
Make sure to answer at least these three questions:

1. What did you do?
2. What did you expect to see?
3. What did you see instead?

General questions should be asked on the Matrix chat instead of the issue
tracker. The developers there will answer or ask you to file an issue if
you've tripped over a bug.


# How to suggest a feature or enhancement

Open an issue on our issues tracker on GitLab which describes the feature you
would like to see, why you need it, and how it should work.


# How to submit patches

If there is not an open issue for what you want to submit, prefer
opening one for discussion before working on merge request (MR). You can work on any
issue that doesn't have an open MR linked to it or a maintainer assigned
to it. These show up in the sidebar. No need to ask if you can work on
an issue that interests you.

Include the following in your patch:

- Use [Black][black] to format your code. This and other tools will run
automatically if you install [pre-commit][pre-commit]. Please read [Pre-commit](#pre-commit)
- Include tests if your patch adds or changes code. Make sure the test
fails without your patch
- Update any relevant docs pages and docstrings. Docstrings are written following
the [Google Style Python Docstrings][sphinx-google]
- Follow the guidelines on [How to Write a Git Commit Message][git-commit].
- The Krake project uses a mechanism known as a Developer Certificate of Origin
(DCO). Please read [Developer Certificate of Origin (DCO)](#developer-certificate-of-origin-dco)


## Pre-commit

To run all pre-commit hooks on your code, go to the Krake project's root directory and run

```bash
pre-commit run
```

By default, pre-commit will only run on the files that have been changed,
meaning those that have been staged in git (i.e. after git add your_script.py).

If you want to manually run all pre-commit hooks on a repository, run

```bash
pre-commit run --all-files
```
Visit [pre-commit usage][pre-commit-usage] guide for further details.

_Our recommendation_ is to configure pre-commit to run on the staged files before every commit
(i.e. git commit), by installing it as a git hook using

```bash
pre-commit install
```


## Developer Certificate of Origin (DCO)

The DCO is a legally binding statement that asserts that you are the
creator of your contribution, and that you wish to allow Krake to use your
work.

Acknowledgement of this permission is done using a sign-off process in Git.
The sign-off is a simple line at the end of the explanation for the patch. The
text of the [DCO](DCO.md) is fairly simple. It is also available on
developercertificate.org.

If you are willing to agree to these terms, you just add a line to every git
commit message:

`Signed-off-by: Joe Smith <joe.smith@email.com>`

If you set your `user.name` and `user.email` as part of your git
configuration, you can sign your commit automatically with `git commit -s`.

Unfortunately, you have to use your real name (i.e., pseudonyms or anonymous
contributions cannot be made). This is because the DCO is a legally binding
document, granting the Krake project to use your work.


<!-- References -->

[krake-matrix]: https://app.element.io/#/room/#krake:matrix.org
[git-commit]: https://chris.beams.io/posts/git-commit/
[sphinx-google]: https://www.sphinx-doc.org/en/master/usage/extensions/example_google.html
[black]: https://black.readthedocs.io
[pre-commit]: https://pre-commit.com
[pre-commit-usage]: https://pre-commit.com/#usage
