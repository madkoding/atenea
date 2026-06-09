#compdef atenea atenea-backup atenea-calendar atenea-contacts atenea-cookbook atenea-docs atenea-gallery atenea-mail atenea-mcp atenea-memory atenea-notes atenea-personal atenea-preset atenea-research atenea-sessions atenea-signature atenea-skills atenea-tasks atenea-theme atenea-webhook
# Zsh tab-completion for the atenea umbrella + sub-CLIs.
#
# Drop in any directory on $fpath, e.g.:
#     fpath=(/path/to/atenea-ui/scripts/_completion $fpath)
#     autoload -U compinit; compinit
#
# Then `atenea <tab>` completes subcommands; `atenea mail <tab>`
# completes mail subcommands; `atenea-mail <tab>` works the same.

_atenea_scripts_dir() {
    local self="${(%):-%x}"
    while [[ -L "$self" ]]; do self="$(readlink "$self")"; done
    cd "${self:h}/.." && pwd
}

typeset -gA _atenea_subs

_atenea_refresh() {
    _atenea_subs=()
    local dir="$(_atenea_scripts_dir)"
    local py="$dir/../venv/bin/python"
    [[ -x "$py" ]] || py="$(command -v python3)"
    local f sub help_out commands
    for f in "$dir"/atenea-*; do
        [[ -x "$f" ]] || continue
        case "$f" in
            *.bak|*.pyc|*.pre-*) continue ;;
        esac
        sub="${${f:t}#atenea-}"
        help_out=$("$py" "$f" --help 2>/dev/null) || continue
        commands=$(echo "$help_out" | grep -oE '\{[a-z0-9_,-]+\}' | head -1 \
            | tr -d '{}' | tr ',' ' ')
        _atenea_subs[$sub]="$commands"
    done
}

_atenea() {
    [[ ${#_atenea_subs} -eq 0 ]] && _atenea_refresh

    local cmd="${words[1]}"

    if [[ "$cmd" == "atenea" ]]; then
        if (( CURRENT == 2 )); then
            local -a subs=(${(k)_atenea_subs} help)
            _describe 'subcommand' subs
            return
        fi
        local sub="${words[2]}"
        if [[ "$sub" == "help" ]] && (( CURRENT == 3 )); then
            local -a subs=(${(k)_atenea_subs})
            _describe 'subcommand' subs
            return
        fi
        if (( CURRENT == 3 )); then
            local -a sc=(${(s/ /)_atenea_subs[$sub]})
            _describe 'command' sc
            return
        fi
        return
    fi

    # atenea-foo <tab>
    local sub="${cmd#atenea-}"
    if (( CURRENT == 2 )); then
        local -a sc=(${(s/ /)_atenea_subs[$sub]})
        _describe 'command' sc
        return
    fi
}

_atenea "$@"
