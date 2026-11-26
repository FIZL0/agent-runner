"""C56: a pick sheet's copy and its buttons on a Needs you card.

Part of `ui_model`: `ui_model` runs this file in its own namespace (see its end). Not imported on its own."""

def sheet_copy(tid: str) -> dict:
    """F411: {copy, page} of `tid`'s pick sheet that has no claude.ai page: the run page's own copy, as a file and where
    the run page shows it; {} for none."""
    from agent_runner import sheet
    from agent_runner.brief import has_sheet
    copy = concept_copy(sheet.local_id(tid)) if has_sheet(tid) else ''
    return {'copy': copy, 'page': sheet.local_page(tid)[1:]} if copy else {}


SHEET_GO_LABEL = 'Go with the recommended picks'


def sheet_options(tid: str, text: str = '') -> list[dict]:
    """F181b: the easy answers of `tid`'s pick sheet as a DECIDE's options, each {name, rec, send}, `send` the reply
    that settles the item (`answer_argv`): the recommended picks, and with one question each of its answers. [] with no
    sheet, one that does not read, one that `text` (the task's) says was answered already, or an item with inputs."""
    from agent_runner import sheet
    from agent_runner.brief import has_sheet
    if not has_sheet(tid) or need_detail.asks_file(tid).get('inputs'):
        return []
    try:
        spec = sheet.load(S.C.notes('sheets', f'{tid}.json'))
        qs = sheet.questions(spec)
        # the sheet file outlives its answer, and an old sheet must not answer a new ask
        if 'picks on the sheet:' in text:
            seen = ' '.join(text.split())
            heads = [x.split('): ', 1)[0] for x in (sheet.picks_note({'groups': [{'questions': [q]}]}, {}).split(': ', 1)[1] for q in qs)]
            if all(' '.join(f'{h}): '.split()) in seen for h in heads):
                return []
        out = [{'name': SHEET_GO_LABEL, 'rec': False, 'send': SHEET_GO[0]}]
        if len(qs) == 1:
            q = qs[0]
            names = [' '.join(str(a).replace('`', '').split()) for a in q['answers']]
            if all(0 < len(n) <= need_detail.OPTION_LEN and n.isprintable() for n in names) and \
                    len({n.casefold() for n in [SHEET_GO_LABEL, *names]}) == len(names) + 1:
                out += sorted(({'name': n, 'rec': j == sheet.rec(q), 'send': f'{tid} picks: {q["id"]}={chr(97 + j)}'}
                               for j, n in enumerate(names)), key=lambda o: not o['rec'])
        return out
    except Exception:  # noqa: BLE001 - a sheet that does not read: its page and the reply are still there
        return []


