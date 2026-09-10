#!/usr/bin/env python3
"""Test diagnostic (non destructif) : Set operation="add" sur IPHostGroup
fusionne-t-il au lieu de remplacer toute la HostList ?

Sert à vérifier si ban peut passer de 3 appels API (create/get/set) à 2 en
évitant le Get préalable avant chaque ajout de membre au groupe.

Résultat déjà établi (voir CHANGELOG) : NON, operation="add" sur un groupe
existant échoue TOUJOURS — confirmé deux fois en réel : avec un host fictif
(501 "Configuration parameters validation failed") et avec un host réel
(502 "Entity having same name already exists" — l'entité en conflit est le
GROUPE, pas le membre ; ne pas confondre avec un signal "membre déjà
présent", ça a causé un bug silencieux en prod, voir CHANGELOG 1.6.1).
ban/unban gardent le schéma get-puis-set. Ce script ne fait donc plus que
documenter/re-vérifier ce point si besoin (ex: après une mise à jour
firmware Sophos).

/!\ Un second test (Remove ciblé sur un membre) a été supprimé de ce script :
confirmé DANGEREUX et reproductible sur firewall réel — au lieu de retirer
le seul membre visé, il a vidé tout le groupe et laissé l'objet dans un état
où même un Set operation="update" normal échoue ensuite (500). Ne JAMAIS
utiliser <Remove><IPHostGroup>...<HostList>...</HostList></IPHostGroup></Remove>
dans ce projet.

À lancer contre un groupe de TEST (jamais la prod). État du groupe restauré
automatiquement à la fin du test (aucun effet de bord observé sur l'échec 501).

Usage:
    ./test_group_merge.py --group Fail2Ban-Test [--config /usr/local/etc/sophos-fw/api.conf]

Prérequis : au moins 2 membres déjà présents dans le groupe de test, par
exemple via :
    sophos_fw_block.py ban 10.0.0.1 --group Fail2Ban-Test
    sophos_fw_block.py ban 10.0.0.2 --group Fail2Ban-Test
"""

import argparse
import logging

import sophos_fw_block as m


def test_set_add(cfg, before):
    print("\n--- Test : Set operation=\"add\" avec un seul membre ---")
    new_name = "f2b_10_0_0_99"
    body = (
        '<Set operation="add"><IPHostGroup>'
        f"<Name>{cfg['group']}</Name>"
        f"<HostList><Host>{new_name}</Host></HostList>"
        "</IPHostGroup></Set>"
    )
    root = m.api_call(cfg, body)
    code, text = m.parse_status(root, "IPHostGroup")
    print("Set operation=add ->", code, text)

    after = m.get_group_hosts(cfg)
    print("APRES add:", after)
    if set(before) <= set(after) and new_name in after:
        print(">>> FUSION confirmée : operation=\"add\" ajoute sans écraser")
    else:
        print(">>> PAS de fusion : operation=\"add\" remplace, garder read-then-write")

    m.set_group_hosts(cfg, before)  # restaure l'état initial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", required=True, help="groupe de TEST (jamais la prod)")
    parser.add_argument("--config", default=m.DEFAULT_CONFIG_PATH)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    cfg = m.load_config(args.config)
    cfg["group"] = args.group

    before = m.get_group_hosts(cfg)
    print("AVANT:", before)
    if len(before) < 2:
        print(
            "ATTENTION: moins de 2 membres dans le groupe, seed-le d'abord "
            "(voir docstring) pour un test représentatif."
        )

    test_set_add(cfg, before)

    print("\ngroupe final (doit être identique à AVANT):", m.get_group_hosts(cfg))


if __name__ == "__main__":
    main()
