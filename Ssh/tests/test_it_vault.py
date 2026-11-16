"""Fin de la fixture `vault` du socle d'intégration (`tests/integration/itbase.py`, `finish_vault`), sans réseau ni vrai
`bw` : un faux client `bw` à liste d'éléments. Un élément de ce run resté après `cleanup`, ou dont la suppression par
`cleanup` a échoué, puis supprimé par la purge de fin (et absent de son contrôle final) n'est pas une erreur : une ligne du
rapport le dit ; un reste après la purge reste une erreur (story 23)."""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "integration"))
import itbase as it  # noqa: E402
from accounts import Scrub  # noqa: E402


def item(iid, run=it.RUN):
    return {"id": iid, "name": "n-" + iid, "fields": [{"name": it.MARK, "value": run, "type": 0}]}


def done(args, out="", rc=0, err=""):
    return subprocess.CompletedProcess(args, rc, out, err)


class FakePop:
    """`Bw` à éléments en mémoire.
    `late` : éléments qui n'apparaissent qu'à la première synchronisation (le contrôle final de `cleanup` les voit, pas sa
    liste de départ). `trash` : identifiants rangés à la corbeille (vus par `list items --trash` seulement).
    `undeletable` : suppression refusée (code 1). `ghost` : suppression « réussie » sans effet (l'élément reste).
    `fail_first` : première suppression refusée, les suivantes réussissent. `ghost_first` : première suppression sans effet.
    `get_fail_first` : première relecture (`get item`) en erreur. `boom_on_sync` : numéros de synchronisation (1 : celle de
    `cleanup`, 2 : début de la purge, 3 : son contrôle final) qui lèvent une exception ; `sync_fail` : qui rendent le code 1 ;
    `list_fail_from_sync` : les listes échouent une fois ce nombre de synchronisations atteint. `vanish` : {numéro de
    synchronisation : ids} supprimés par un tiers à ce moment ; `unmark` : idem, la marque du run retirée (l'élément reste). `noid` : éléments marqués sans identifiant, toujours listés."""

    def __init__(self, items, late=(), trash=(), undeletable=(), ghost=(), fail_first=(), ghost_first=(), get_fail_first=(),
                 boom_on_sync=(), sync_fail=(), list_fail_from_sync=None, vanish=None, unmark=None, noid=0):
        self.items = {i["id"]: i for i in items}
        self.late = list(late)
        self.trash = set(trash)
        self.undeletable, self.ghost, self.fail_first = set(undeletable), set(ghost), set(fail_first)
        self.ghost_first, self.get_fail_first = set(ghost_first), set(get_fail_first)
        self.boom_on_sync, self.sync_fail = set(boom_on_sync), set(sync_fail)
        self.list_fail_from_sync, self.vanish = list_fail_from_sync, dict(vanish or {})
        self.unmark = dict(unmark or {})
        self.noid = [{"name": "sans-id", "fields": [{"name": it.MARK, "value": it.RUN, "type": 0}]} for _ in range(noid)]
        self.syncs = 0
        self.blocked = 0
        self.deleted = []

    def sync(self, session):
        self.syncs += 1
        if self.syncs in self.boom_on_sync:
            raise RuntimeError("panne de sync %d" % self.syncs)
        for iid in self.vanish.get(self.syncs, ()):
            self.items.pop(iid, None)
        for iid in self.unmark.get(self.syncs, ()):  # marque retirée (modifiée à la main, par exemple) : toujours là, non marqué
            if iid in self.items:
                self.items[iid] = {"id": iid, "name": "n-" + iid, "fields": []}
        if self.syncs in self.sync_fail:
            return done(["sync"], rc=1, err="sync en échec")
        for i in self.late:
            self.items[i["id"]] = i
        self.late = []
        return done(["sync"])

    def run(self, *args, session=None):
        if args[:2] == ("list", "items"):
            if self.list_fail_from_sync is not None and self.syncs >= self.list_fail_from_sync:
                return done(args, rc=1, err="liste en échec")
            trash = "--trash" in args
            listed = [i for i in self.items.values() if (i["id"] in self.trash) == trash] + ([] if trash else self.noid)
            return done(args, json.dumps(listed))
        if args[:2] == ("get", "item"):
            if args[2] in self.get_fail_first:
                self.get_fail_first.discard(args[2])
                return done(args, rc=1, err="relecture en panne")
            i = self.items.get(args[2])
            return done(args, json.dumps(i)) if i else done(args, rc=1, err="Not found.")
        raise AssertionError("appel inattendu : %r" % (args,))

    def delete(self, iid, session):
        if iid in self.undeletable:
            return done(["delete", iid], rc=1, err="refusé")
        if iid in self.fail_first:
            self.fail_first.discard(iid)
            return done(["delete", iid], rc=1, err="panne passagère")
        self.deleted.append(iid)
        if iid in self.ghost_first:
            self.ghost_first.discard(iid)
        elif iid not in self.ghost:
            self.items.pop(iid, None)
        return done(["delete", iid])


@pytest.fixture
def report():
    return it.Report(Scrub([]))


def finish(pop, report, created):
    return it.finish_vault(pop, "session", created, report)


def purge_lines(report):
    return [l for l in report.lines if "supprimé par la purge" in l]


def vault_lines(report):
    """Lignes de rapport d'un élément de ce run (« nettoyage : élément <id> de ce run : … »), texte exact."""
    return [l for l in report.lines if l.startswith("nettoyage : élément ")]


def test_rien_ne_reste(report):
    pop = FakePop([item("a"), item("b")])
    assert finish(pop, report, ["a", "b"]) == []
    assert pop.items == {} and not purge_lines(report)


def test_restes_supprimes_par_la_purge_pas_une_erreur(report):
    """Deux éléments de ce run restés après `cleanup` (vus à son contrôle final), supprimés par la purge de fin."""
    pop = FakePop([item("a")], late=[item("x1"), item("x2")])
    problems = finish(pop, report, ["a"])
    assert problems == [], problems
    assert pop.items == {}, "tout supprimé"
    assert vault_lines(report) == ["nettoyage : élément x1 de ce run : resté après cleanup, supprimé par la purge",
                                   "nettoyage : élément x2 de ce run : resté après cleanup, supprimé par la purge"], report.lines


def test_reste_a_la_corbeille_seulement(report):
    """Un reste visible seulement avec `--trash` (cleanup et purge le listent) : supprimé par la purge, pas une erreur ;
    s'il résiste, erreur."""
    pop = FakePop([], late=[item("t1")], trash={"t1"})
    assert finish(pop, report, []) == []
    assert pop.items == {} and vault_lines(report) == [
        "nettoyage : élément t1 de ce run : resté après cleanup, supprimé par la purge"], report.lines
    pop = FakePop([], late=[item("t2")], trash={"t2"}, undeletable={"t2"})
    assert any("encore présents" in p for p in finish(pop, report, []))


def test_reste_apres_la_purge_est_une_erreur(report):
    """Éléments que la purge ne peut pas supprimer : erreur (le reste est réel) ; l'autre est dit supprimé par la purge."""
    pop = FakePop([item("a")], late=[item("x1"), item("x2")], undeletable={"x2"})
    problems = finish(pop, report, ["a"])
    assert any("encore présents" in p for p in problems), problems
    assert "x2" in pop.items and "x1" not in pop.items
    assert any("1 élément(s) de ce run encore présents après le nettoyage et la purge" in p for p in problems), problems
    assert vault_lines(report) == ["nettoyage : élément x1 de ce run : resté après cleanup, supprimé par la purge"], report.lines


def test_suppression_sans_effet_pas_supprime_par_la_purge(report):
    """La purge croit supprimer (code 0), l'élément est toujours dans son contrôle final : erreur, et aucune ligne
    « supprimé par la purge »."""
    pop = FakePop([], late=[item("x1")], ghost={"x1"})
    problems = finish(pop, report, [])
    assert any("encore présents (fin)" in p for p in problems), problems
    assert any("après le nettoyage et la purge" in p for p in problems), problems
    assert pop.deleted == ["x1"], "la purge a bien essayé"
    assert not purge_lines(report), report.lines


def test_echec_de_suppression_puis_purge_est_une_ligne_de_rapport(report):
    """`cleanup` n'arrive pas à supprimer `a` (code 1), la purge y arrive : pas une erreur, une ligne du rapport, une seule."""
    pop = FakePop([item("a")], fail_first={"a"})
    problems = finish(pop, report, ["a"])
    assert problems == [], problems
    assert pop.items == {}
    assert vault_lines(report) == [
        "nettoyage : élément a de ce run : resté après cleanup, supprimé par la purge ; "
        "suppression échouée, purgé ensuite (suppression de a : panne passagère)"], report.lines


def test_relecture_en_panne_puis_purge(report):
    pop = FakePop([item("a")], get_fail_first={"a"})
    assert finish(pop, report, ["a"]) == []
    assert vault_lines(report) == [
        "nettoyage : élément a de ce run : resté après cleanup, supprimé par la purge ; "
        "suppression échouée, purgé ensuite (relecture de a : relecture en panne)"], report.lines


def test_encore_lisible_apres_suppression_puis_purge(report):
    """Première suppression sans effet (encore lisible), la purge supprime pour de bon."""
    pop = FakePop([item("a")], ghost_first={"a"})
    assert finish(pop, report, ["a"]) == []
    assert vault_lines(report) == [
        "nettoyage : élément a de ce run : resté après cleanup, supprimé par la purge ; "
        "suppression échouée, purgé ensuite (a encore lisible après suppression)"], report.lines


def test_un_element_resté_et_en_echec_une_seule_ligne(report):
    """Id à la fois resté après `cleanup` (vu au contrôle final) et en échec de suppression : une ligne, les deux causes."""
    pop = FakePop([item("a")], fail_first={"a"})
    assert finish(pop, report, ["a"]) == []
    assert len(vault_lines(report)) == 1, report.lines
    assert "resté après cleanup" in vault_lines(report)[0] and "suppression échouée" in vault_lines(report)[0]


def test_echec_de_suppression_jamais_purge_est_une_erreur(report):
    pop = FakePop([item("a")], undeletable={"a"})
    problems = finish(pop, report, ["a"])
    assert any("suppression de a" in p for p in problems), problems
    assert not [l for l in report.lines if "purgé ensuite" in l]


def test_parti_quel_que_soit_celui_qui_l_a_supprime(report):
    """Absent du contrôle final de la purge, même supprimé par un tiers (ni `cleanup` ni la purge) : parti, pas une erreur."""
    pop = FakePop([item("a")], fail_first={"a"}, vanish={2: {"a"}})
    assert finish(pop, report, ["a"]) == []
    assert pop.deleted == [], "ni cleanup ni la purge ne l'ont supprimé"
    # la ligne ne dit pas « supprimé par la purge » : un tiers l'a supprimé
    assert vault_lines(report) == [
        "nettoyage : élément a de ce run : resté après cleanup, absent du contrôle final (supprimé hors purge) ; "
        "suppression échouée, absent du contrôle final (supprimé hors purge) (suppression de a : panne passagère)"], report.lines
    assert not purge_lines(report) and not [l for l in report.lines if "purgé ensuite" in l]


def test_marque_retiree_ne_vaut_pas_parti(report):
    """Un élément du run dont la marque a disparu (toujours dans les listes, non marqué) n'est pas « parti » : la purge ne le
    voit plus comme marqué, mais il est présent par identifiant au contrôle final : erreur, aucune ligne de rapport."""
    pop = FakePop([item("a")], fail_first={"a"}, unmark={2: {"a"}})
    problems = finish(pop, report, ["a"])
    assert "a" in pop.items and pop.deleted == [], "toujours dans le coffre, jamais supprimé"
    assert "suppression de a : panne passagère" in problems, problems
    assert "1 élément(s) de ce run encore présents après le nettoyage et la purge" in problems, problems
    assert vault_lines(report) == [], report.lines


@pytest.mark.parametrize("panne", [dict(sync_fail={3}), dict(list_fail_from_sync=3)])
def test_controle_final_illisible_tout_reste_une_erreur(report, panne):
    """Sync final en échec (liste du cache local) ou liste finale en échec : rien n'est prouvé, les restes sont des erreurs,
    aucune ligne « supprimé par la purge »."""
    pop = FakePop([item("a")], late=[item("x")], fail_first={"a"}, **panne)
    problems = finish(pop, report, ["a"])
    assert any("après le nettoyage et la purge" in p for p in problems), problems
    assert any("suppression de a" in p for p in problems), problems
    assert not purge_lines(report) and not [l for l in report.lines if "purgé ensuite" in l], report.lines


def test_element_marque_sans_identifiant_signale_sans_confondre_avec_l_illisible(report):
    """Sans `id` : écarté et signalé ; le contrôle final reste lisible, les autres éléments restent traités."""
    pop = FakePop([], late=[item("x")], noid=1)
    problems = finish(pop, report, [])
    # un seul message, malgré les quatre relevés (début et contrôle final de `cleanup` et de la purge)
    assert problems == ["1 élément(s) marqué(s) sans identifiant : ni suivis ni supprimés"], problems
    assert pop.items == {} and vault_lines(report) == [
        "nettoyage : élément x de ce run : resté après cleanup, supprimé par la purge"], "x reconnu parti malgré l'élément sans id"


def test_cleanup_qui_leve_n_empeche_pas_la_purge(report):
    """`cleanup` lève avant que `x` n'apparaisse : seule la purge peut le supprimer."""
    pop = FakePop([item("a")], late=[item("x")], boom_on_sync={1})
    problems = finish(pop, report, ["a"])
    assert len(problems) == 1 and problems[0].startswith("nettoyage interrompu : RuntimeError"), problems
    assert pop.items == {} and pop.syncs == 3, "la purge a eu lieu (sync de début et contrôle final)"
    assert [l for l in report.lines if l.startswith("purge des éléments") and "supprimés=1" in l and "restants=0" in l], report.lines


def test_purge_qui_leve_est_une_erreur_et_rien_n_est_prouve(report):
    pop = FakePop([], late=[item("x1")], boom_on_sync={2})
    problems = finish(pop, report, [])
    assert any("purge interrompue : RuntimeError" in p for p in problems), problems
    assert any("après le nettoyage et la purge" in p for p in problems), problems
    assert not purge_lines(report)


def test_cleanup_seul_garde_son_comportement(report):
    """Sans `left_ids` ni `item_problems`, `cleanup` compte toujours les restes et les échecs comme des problèmes."""
    pop = FakePop([], late=[item("x1")])
    assert [p for p in it.cleanup(pop, "session", [], report) if "encore présents" in p] == ["1 élément(s) de ce run encore présents"]
    pop = FakePop([item("a")], undeletable={"a"})
    assert any("suppression de a" in p for p in it.cleanup(pop, "session", ["a"], report))


def test_restes_d_un_autre_run_ne_comptent_pas_au_nettoyage(report):
    """Un élément marqué par un autre run n'est pas de ce run : `cleanup` ne le touche pas, la purge (tout run) le supprime."""
    pop = FakePop([item("a"), item("autre", run="autre-run")])
    assert finish(pop, report, ["a"]) == []
    assert pop.items == {}, "supprimé par la purge (marqueur de n'importe quel run)"
