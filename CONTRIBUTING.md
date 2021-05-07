# Introduction

First off all, thank you for considering contributing to Krake!

There are many ways to contribute, such as improving the documentation,
submitting bug reports and feature requests or writing code which can be
incorporated into Krake itself.

Please, don't use the issue tracker for support questions. Connect with us on
the [Krake Matrix room][krake-matrix] if you  have any questions or need
support.


# Developer Certificate of Origin (DCO)

The Krake project uses a mechanism known as a Developer Certificate of Origin
(DCO). The DCO is a legally binding statement that asserts that you are the
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


# Commit message convention

We follow the guidelines on [How to Write a Git Commit Message][git-commit].


# Docstrings

Docstrings are written following the [Google Style Python Docstrings][sphinx-google].


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


<!-- References -->

[krake-matrix]: https://app.element.io/#/room/#krake:matrix.org
[git-commit]: https://chris.beams.io/posts/git-commit/
[sphinx-google]: https://www.sphinx-doc.org/en/master/usage/extensions/example_google.html
