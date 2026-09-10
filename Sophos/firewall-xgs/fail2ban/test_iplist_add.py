#!/usr/bin/env python3
"""Test diagnostic (non destructif) : Set operation="add" sur un IPHost
de type IP list fusionne-t-il (append) au lieu de remplacer toute la
ListOfIPAddresses ?

Résultat déjà établi (voir CHANGELOG 2.2.2) : NON — confirmé en réel,
502 "Entity having same name already exists", IP list inchangée. Même
comportement que sur IPHostGroup (voir test_group_merge.py) : aucune
sémantique "append" nulle part dans cette API pour un objet nommé déjà
existant, quel que soit son type. Piste fermée pour accélérer ban/unban.

Effet de bord utile de ce test : la restauration en fin de script (Set
operation="update" avec la MÊME liste qu'avant, donc sans changement réel
de contenu) a quand même pris ~8.4s en conditions réelles — preuve que le
coût observé (~5-8s) n'est PAS proportionnel à la taille du diff ni au
fait que le contenu change vraiment : toute écriture réussie sur un objet
référencé par une règle active déclenche le même coût fixe (recompile de
policy, probable). Seuls le batching/debounce (moins d'écritures) ou un
mécanisme différent (liste tirée par le firewall plutôt que poussée)
peuvent réduire l'impact — pas d'optimisation possible côté forme de la
requête.

À lancer contre une IP list de TEST (jamais la prod). État restauré
automatiquement à la fin (replace complet avec la liste d'origine).

Usage:
    ./test_iplist_add.py --iplist Fail2Ban-Test-List [--config /usr/local/etc/sophos-fw/api.conf] [--debug]

Prérequis : l'IP list de test doit déjà exister sur le firewall (onglet
IP Host, type "IP list"), avec au moins une IP dedans pour un test
représentatif (sinon avertissement, le test continue quand même).
"""

import argparse
import logging
import time

import sophos_fw_block as m


def test_add(cfg, before):
    print("\n--- Test : Set operation=\"add\" avec une seule IP ---")
    new_ip = "203.0.113.99"
    body = (
        '<Set operation="add"><IPHost>'
        f"<Name>{cfg['iplist']}</Name>"
        "<HostType>IPList</HostType>"
        f"<ListOfIPAddresses>{new_ip}</ListOfIPAddresses>"
        "</IPHost></Set>"
    )
    t0 = time.monotonic()
    root = m.api_call(cfg, body)
    dt_add = time.monotonic() - t0
    code, text = m.parse_status(root, "IPHost")
    print(f"Set operation=add -> {code} {text} ({dt_add:.3f}s)")

    after = m.get_iplist_addresses(cfg)
    print("APRES add:", after)
    if set(before) <= set(after) and new_ip in after:
        print('>>> FUSION confirmée : operation="add" ajoute sans écraser')
    elif after == before:
        print(
            '>>> PAS de fusion : operation="add" rejetée (502), IP list '
            "inchangée — comme IPHostGroup"
        )
    elif after == [new_ip]:
        print('>>> PAS de fusion : operation="add" a remplacé tout le contenu')
    else:
        print(">>> Résultat inattendu, vérifier manuellement avant d'automatiser")

    print(
        "\n--- Restauration : Set operation=\"update\" avec la MÊME liste "
        "qu'avant (aucun changement réel de contenu) ---"
    )
    t0 = time.monotonic()
    m.set_iplist_addresses(cfg, before)
    dt_update = time.monotonic() - t0
    print(f"operation=update (contenu identique, {len(before)} IP) : {dt_update:.3f}s")

    print(
        f"\nDurées : add rejeté={dt_add:.3f}s vs update accepté (même contenu)"
        f"={dt_update:.3f}s"
    )
    print(
        ">>> Si update reste lent malgré un contenu inchangé : le coût vient "
        "de l'application de la config (recompile probable côté objet "
        "référencé par une règle), pas de la taille du diff ni de add vs "
        "update. Voir docstring pour la conclusion et les pistes restantes."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iplist", required=True, help="IP list de TEST (jamais la prod)"
    )
    parser.add_argument("--config", default=m.DEFAULT_CONFIG_PATH)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--debug-timing",
        action="store_true",
        help="log la durée de chaque appel API et de la connexion TCP+TLS",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if (args.debug or args.debug_timing) else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    m.DEBUG_TIMING = args.debug_timing
    if args.debug_timing:
        m._patch_connection_timing()

    cfg = m.load_config(args.config)
    cfg["iplist"] = args.iplist

    before = m.get_iplist_addresses(cfg)
    print("AVANT:", before)
    if not before:
        print(
            "ATTENTION: IP list de test vide, ajoute au moins une IP d'abord "
            "pour un test représentatif (voir docstring)."
        )

    test_add(cfg, before)

    print("\nIP list finale (doit être identique à AVANT):", m.get_iplist_addresses(cfg))


if __name__ == "__main__":
    main()
