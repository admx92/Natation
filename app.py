
import csv
import inspect
from bisect import bisect_left
from pathlib import Path


import streamlit as st

st.set_page_config(
    page_title="Chrono Natation",
    page_icon="icon.png",
    layout="centered"
)

st.markdown("""
<style>
.block-container {
    max-width: 590px;
    padding: 1rem 1rem 3rem;
}
h1 {
    font-size: 2rem !important;
    margin-bottom: .1rem;
}
div[data-testid="stNumberInput"] input {
    font-size: 1.35rem;
    text-align: center;
}
.result {
    border-radius: 16px;
    padding: 17px 19px;
    margin: 11px 0;
    background: #edf4fa;
    color: #132b40;
}
.result .label {
    font-size: .95rem;
    opacity: .8;
}
.result .value {
    font-size: 1.75rem;
    font-weight: 800;
    line-height: 1.35;
}
.good {
    background: #e4f7e9;
    color: #11642e;
}
.bad {
    background: #ffe8e8;
    color: #a11724;
}
.neutral {
    background: #f0f1f4;
    color: #424651;
}

/* Boutons plus faciles à toucher sur iPhone */
div[data-testid="stSegmentedControl"] button {
    min-height: 44px;
    font-size: 1rem;
}
</style>
""", unsafe_allow_html=True)


# ==================================================
# DONNEES FFN
# ==================================================

EVENTS = [
    "50 NL", "100 NL", "200 NL", "400 NL",
    "800 NL", "1500 NL",
    "50 dos", "100 dos", "200 dos",
    "50 brasse", "100 brasse", "200 brasse",
    "50 pap", "100 pap", "200 pap",
    "200 4N", "400 4N"
]

# Grilles de qualification 2026 pour les U15
# Ces valeurs seront remplacées ultérieurement
# par une lecture directe sur le site FFN.



# Majorations officielles 25 m vers 50 m
# Valeurs en centièmes

CONVERSION = {
    "Dames": [
        70, 120, 290, 620, 1290, 2450,
        130, 230, 540, 70, 190, 450,
        60, 140, 330, 340, 750
    ],
    "Messieurs": [
        70, 150, 360, 770, 1590, 3010,
        150, 300, 690, 110, 250, 590,
        70, 140, 330, 410, 900
    ],
}

DISTANCES = {
    "NL": ["50", "100", "200", "400", "800", "1500"],
    "dos": ["50", "100", "200"],
    "brasse": ["50", "100", "200"],
    "pap": ["50", "100", "200"],
    "4N": ["100", "200", "400"],
    "relais": [
        "4x100 NL",
        "4x100 4N",
        "4x200 NL",
        "10x50 NL"
    ],
}


# ==================================================
# FONCTIONS
# ==================================================

def centiemes(t):
    t = str(t).strip().replace(",", ".")
    morceaux = t.split(":")

    if len(morceaux) == 2:
        minutes = int(morceaux[0])
        sec = morceaux[1]
    else:
        minutes = 0
        sec = morceaux[0]

    s, _, c = sec.partition(".")
    return (minutes * 60 + int(s)) * 100 + int((c + "00")[:2])


def chrono(cs):
    m, reste = divmod(cs, 6000)
    s, c = divmod(reste, 100)
    return f"{m}:{s:02d}.{c:02d}" if m else f"{s:02d}.{c:02d}"


def tuile(label, contenu, style=""):
    st.markdown(
        f'<div class="result {style}">'
        f'<div class="label">{label}</div>'
        f'<div class="value">{contenu}</div>'
        f'</div>',
        unsafe_allow_html=True
    )


def boutons(label, options, default, key=None, format_func=None):
    """
    Affiche des boutons Streamlit.
    Les options passent sur plusieurs lignes sur iPhone
    lorsque la version de Streamlit le permet.
    """
    arguments = {
        "label": label,
        "options": options,
        "default": default,
        "key": key,
    }

    if format_func is not None:
        arguments["format_func"] = format_func

    parametres = inspect.signature(st.segmented_control).parameters

    if "wrap" in parametres:
        arguments["wrap"] = True

    return st.segmented_control(**arguments)


def temps_ffn_en_centiemes(valeur):
    minutes, point, suite = str(valeur).strip().partition(".")

    if (
        not point
        or len(suite) != 4
        or not minutes.isdigit()
        or not suite.isdigit()
    ):
        raise ValueError(f"Temps FFN non reconnu : {valeur!r}")

    secondes = int(suite[:2])
    centiemes_valeur = int(suite[2:])

    # 18.6000 = 19 minutes
    if secondes > 60:
        raise ValueError(f"Secondes FFN invalides : {valeur!r}")

    return (
        (int(minutes) * 60 + secondes) * 100
        + centiemes_valeur
    )


def libelle_epreuve(nage, distance, sexe):
    noms = {
        "NL": "Nage Libre",
        "dos": "Dos",
        "brasse": "Brasse",
        "pap": "Papillon",
        "4N": "4 Nages",
    }

    if nage == "relais":
        relais = {
            "4x100 NL": "4x100 Nage Libre",
            "4x100 4N": "4x100 4 Nages",
            "4x200 NL": "4x200 Nage Libre",
            "4x200 4N": "4x200 4 Nages Individuel",
            "10x50 NL": "10x50 Nage Libre",
        }
        base = relais[distance]
    else:
        base = f"{distance} {noms[nage]}"

    return f"{base} {sexe}"


@st.cache_data(show_spinner="Chargement de la cotation FFN…")
def lire_points():
    dossier = Path(__file__).parent

    chemin_epreuves = dossier / "ffnex_liste_epreuve.csv"
    chemin_cotation = dossier / "ffnex_table_cotation.csv"

    absents = [
        p.name
        for p in (chemin_epreuves, chemin_cotation)
        if not p.is_file()
    ]

    if absents:
        return {}, {}, (
            "Fichier(s) absent(s) : " + ", ".join(absents)
        )

    try:
        with chemin_epreuves.open(
            encoding="latin-1", newline=""
        ) as fichier:
            codes = {
                ligne["EPREUVE_LABEL"].strip():
                int(ligne["EPREUVE_ID"])
                for ligne in csv.DictReader(fichier, delimiter=";")
            }

        cotations = {}

        with chemin_cotation.open(
            encoding="utf-8-sig", newline=""
        ) as fichier:
            for ligne in csv.DictReader(fichier, delimiter=";"):
                code = int(ligne["EPREUVE_ID"])
                temps = temps_ffn_en_centiemes(ligne["TEMPS"])
                points = int(ligne["POINTS"])

                cotations.setdefault(code, []).append(
                    (temps, points)
                )

        for lignes in cotations.values():
            lignes.sort(key=lambda x: x[0])

        return codes, cotations, None

    except (KeyError, ValueError, OSError, UnicodeError) as e:
        return {}, {}, f"Erreur de lecture CSV : {e}"


def chercher_points(
    codes, cotations, sexe, nage, distance, temps
):
    libelle = libelle_epreuve(nage, distance, sexe)
    code = codes.get(libelle)

    if code is None:
        return None, (
            f"Épreuve absente de la liste FFN : {libelle}"
        )

    lignes = cotations.get(code)

    if not lignes:
        return None, (
            f"Aucune cotation FFN pour : {libelle}"
        )

    # Premier chrono FFN supérieur ou égal
    index = bisect_left(lignes, (temps, -1))

    if index >= len(lignes):
        return None, (
            "Chrono au-delà du dernier temps de la table FFN."
        )

    return lignes[index][1], None



# ==================================================
# QUALIFICATIONS FFN - LECTURE DU CSV
# ==================================================

COMPETITIONS = [
    "Challenge national",
    "France U18",
    "France Élite",
]


@st.cache_data
def lire_qualifications():
    fichier = Path(__file__).parent / "qualifications_ffn.csv"

    if not fichier.exists():
        return {}, "Fichier qualifications_ffn.csv absent."

    try:
        grilles = {}

        with fichier.open(
            encoding="utf-8-sig",
            newline=""
        ) as f:
            lecteur = csv.DictReader(f, delimiter=";")

            for ligne in lecteur:
                if ligne["saison"] != "2026":
                    continue

                cle = (
                    ligne["competition"],
                    ligne["sexe"],
                    ligne["age"],
                    ligne["epreuve"]
                )

                grilles[cle] = int(ligne["temps_centiemes"])

        return grilles, None

    except (OSError, ValueError, KeyError) as erreur:
        return {}, f"Erreur de lecture CSV : {erreur}"


def chercher_limite_ffn(
    competition, sexe, age, nage, distance
):
    grilles, erreur = lire_qualifications()

    if erreur:
        return None, erreur

    if competition == "France U18" and age == "Senior":
        return None, "Non applicable aux Seniors."

    epreuve = f"{distance} {nage}"

    cle = (competition, sexe, age, epreuve)

    limite = grilles.get(cle)

    if limite is None:
        return None, "Aucun seuil pour cette catégorie."

    return limite, None




# ==================================================
# INTERFACE PRINCIPALE : COTATION FFN
# ==================================================

st.title("🏊 Chrono Natation")
st.caption("Cotation fédérale FFN")

# Sexe
sexe = boutons(
    "Sexe",
    ["Dames", "Messieurs"],
    "Dames",
    key="sexe"
)

# Nage
nage = boutons(
    "Nage",
    ["NL", "dos", "brasse", "pap", "4N", "relais"],
    "NL",
    key="nage",
    format_func=lambda x: {
        "NL": "NL",
        "dos": "Dos",
        "brasse": "Brasse",
        "pap": "Pap",
        "4N": "4N",
        "relais": "Relais",
    }[x]
)

# Distance adaptée à la nage
if st.session_state.get("nage_precedente") != nage:
    st.session_state["distance"] = DISTANCES[nage][0]
    st.session_state["nage_precedente"] = nage

if st.session_state.get("distance") not in DISTANCES[nage]:
    st.session_state["distance"] = DISTANCES[nage][0]

distance = boutons(
    "Distance",
    DISTANCES[nage],
    DISTANCES[nage][0],
    key="distance"
)

# Chrono
st.markdown("**Temps réalisé**")

a, b, c = st.columns(3)

with a:
    minute = st.number_input(
        "Minutes", 0, 999, 0, step=1
    )

with b:
    seconde = st.number_input(
        "Secondes", 0, 59, 30, step=1
    )

with c:
    centieme = st.number_input(
        "Centièmes", 0, 99, 0, step=1
    )

temps = (minute * 60 + seconde) * 100 + centieme
epreuve = f"{distance} {nage}"

# ==================================================
# 1. COTATION AUTOMATIQUE
# ==================================================

if temps > 0:

    codes, cotations, erreur = lire_points()

    if not erreur:
        points, erreur_epreuve = chercher_points(
            codes, cotations, sexe, nage, distance, temps
        )
    else:
        points, erreur_epreuve = None, None

    if points is not None:
        tuile(
            "Cotation fédérale",
            f"{points} points"
        )
    else:
        tuile(
            "Cotation fédérale",
            "Non disponible",
            "neutral"
        )
        st.caption(
            erreur or erreur_epreuve
            or "Épreuve ou chrono introuvable."
        )

else:
    st.info("Entre un temps supérieur à zéro.")

# ==================================================
# 2. QUALIFICATIONS FACULTATIVES
# ==================================================

st.divider()

with st.expander("🏆 Qualifications — Voir le détail"):

    st.caption(
        "Comparaison avec les temps de qualification FFN"
    )

    # Âge : uniquement pour les qualifications
    age = boutons(
        "Catégorie d'âge",
        ["U14", "U15", "U16", "U17", "U18", "Senior"],
        "U15",
        key="age"
    )

    # Bassin : uniquement pour les qualifications
    bassin = boutons(
        "Bassin",
        [25, 50],
        50,
        key="bassin",
        format_func=lambda x: f"{x} m"
    )

    if temps <= 0:
        st.info("Entre d'abord un temps réalisé.")

    else:
        # Conversion éventuelle en bassin de 50 m
        if bassin == 50:
            temps_50 = temps

            tuile(
                "Temps bassin de 50 m",
                chrono(temps_50)
            )

        elif epreuve in EVENTS:
            idx = EVENTS.index(epreuve)
            majoration = CONVERSION[sexe][idx]

            temps_50 = temps + majoration

            tuile(
                "Équivalent bassin de 50 m",
                chrono(temps_50)
            )

            st.caption(
                f"Majoration FFN : +{majoration / 100:.2f} s"
            )

        else:
            temps_50 = None

            tuile(
                "Équivalent bassin de 50 m",
                "Non disponible",
                "neutral"
            )

        
        # Résultats des qualifications FFN en direct
        st.markdown("#### Temps de qualification")

        if epreuve not in EVENTS or temps_50 is None:
            st.info(
                "Aucune grille individuelle 50 m "
                "applicable à cette épreuve."
            )

        else:
            for competition in COMPETITIONS:

                limite, erreur_qualif = chercher_limite_ffn(
                    competition,
                    sexe,
                    age,
                    nage,
                    distance
                )

                if erreur_qualif:
                    tuile(
                        competition,
                        "Non disponible",
                        "neutral"
                    )
                    st.caption(erreur_qualif)
                    continue

                ecart = temps_50 - limite

                if ecart <= 0:
                    tuile(
                        f"{competition} · limite {chrono(limite)}",
                        "✓ OUI",
                        "good"
                    )
                else:
                    tuile(
                        f"{competition} · limite {chrono(limite)}",
                        f"− {chrono(ecart)} à gagner",
                        "bad"
                    )



        if bassin == 25:
            st.warning(
                "Conversion indicative : "
                "un chrono converti ne garantit pas "
                "une qualification officielle."
            )

st.caption("Données de cotation fédérale FFN")
