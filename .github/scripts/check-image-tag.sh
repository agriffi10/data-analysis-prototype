#!/usr/bin/env bash
# Refuses an image tag outside the tag grammar, and never prints the tag it refused.
#
# Usage: check-image-tag.sh <tag>. Exits 0 for an empty tag or a bare one, 1 with a
# `Malformed tag` error for anything else, and 2 when it is not handed exactly one argument.
#
# RUN IT ON A DISPATCH'S `image_tag` BEFORE THE REGISTRY SEES THE VALUE, and before anything prints
# it. Outside the grammar two things go wrong, and escaping the value where it is printed fixes
# only the second:
#
#   * The AWS CLI respells an `imageTag=` value before sending it: it trims whitespace, newlines
#     and carriage returns included, and strips the quotes from around it. ` abc `, `'abc'` and
#     `abc<newline>` are all looked up as `abc`, so a padded or quoted tag is FOUND, then handed on
#     as typed, naming an image the registry does not hold.
#   * The runner reads every line of output that begins `::` as a workflow command, so a value
#     carrying a newline, printed in an error or a notice, emits a second command of the caller's
#     choosing — and written to $GITHUB_OUTPUT, it sets a second output.
#
# Inside the grammar the CLI sends the value verbatim, and the only thing left to print is a tag.
# It is Docker's tag grammar, and every tag this repository pushes is a commit sha.
#
# A WHOLE-STRING MATCH, never `grep`, which is line-oriented and passes a value whose first line is
# a valid tag. Bash compiles `=~` as a POSIX extended expression without REG_NEWLINE, so a newline
# is an ordinary character and `$` matches only at the very end of the string — unlike Python's
# `re`, where `$` also matches before a trailing newline. A newline in any position, the last one
# included, is refused by the match alone.
#
# Exactly one argument, because a caller that forgets to pass the tag would otherwise be told every
# value is fine. An empty tag is passed as an empty argument, and means "this commit".
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "::error::check-image-tag.sh takes exactly one argument, the tag to check, and was given $#."
  exit 2
fi

if [ -z "$1" ]; then
  exit 0
fi

# THE MATCH RUNS IN THE C LOCALE. POSIX leaves what a bracket range like `A-Z` holds to the locale
# anywhere else, and a locale that orders a range by collation can put a non-ASCII letter inside
# it; in the C locale the grammar means exactly the ASCII characters it spells.
LC_ALL=C
TAG_GRAMMAR='^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$'
if [[ "$1" =~ $TAG_GRAMMAR ]]; then
  exit 0
fi

echo "::error title=Malformed tag::the image_tag input is not a bare image tag — letters, digits, '_', '.' and '-', with no spaces or quotes. Name the commit sha the image was pushed under."
exit 1
