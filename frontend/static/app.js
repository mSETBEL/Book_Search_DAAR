// ============================================================
// 1. DONNÉES FACTICES (mock)
//    Même format que la future API. Valeurs inventées.
// ============================================================

const MOCK_RECHERCHE = {
  query: "whale",
  mode: "keyword",
  total: 3,
  time_ms: 12.4,
  results: [
    { id: 42, title: "Moby Dick; Or, The Whale", author: "Herman Melville", occurrences: 1226, centrality: 0.0031, score: 0.94 },
    { id: 17, title: "Twenty Thousand Leagues under the Sea", author: "Jules Verne", occurrences: 58, centrality: 0.0027, score: 0.61 },
    { id: 88, title: "The Sea-Wolf", author: "Jack London", occurrences: 21, centrality: 0.0019, score: 0.33 }
  ],
  suggestions: [
    { id: 187, title: "Captains Courageous", author: "Rudyard Kipling", distance: 0.41 },
    { id: 203, title: "Treasure Island", author: "Robert Louis Stevenson", distance: 0.47 }
  ]
};

const MOCK_LIVRE = {
  id: 42,
  title: "Moby Dick; Or, The Whale",
  author: "Herman Melville",
  word_count: 215000,
  pagerank: 0.0031,
  neighbors: [
    { id: 17, title: "Twenty Thousand Leagues under the Sea", distance: 0.38 },
    { id: 187, title: "Captains Courageous", distance: 0.41 }
  ]
};


// ============================================================
// 2. ACCÈS AU SERVEUR
//    Le SEUL endroit à modifier quand le vrai serveur sera prêt.
// ============================================================

async function api(chemin) {
  // PLUS TARD, remplacer tout le contenu par :
  //   const reponse = await fetch("/api" + chemin);
  //   return await reponse.json();

  if (chemin.startsWith("/books/")) return MOCK_LIVRE;
  return MOCK_RECHERCHE;
}


// ============================================================
// 3. OUTILS
// ============================================================

// Affiche une seule vue et cache les autres
function afficher(idVue) {
  const vues = ["vue-accueil", "vue-resultats", "vue-livre", "vue-erreur"];
  for (const id of vues) {
    document.getElementById(id).hidden = (id !== idVue);
  }
}

// Empêche un titre contenant du HTML de casser la page
function echapper(texte) {
  const div = document.createElement("div");
  div.textContent = texte;
  return div.innerHTML;
}


// ============================================================
// 4. RECHERCHE
// ============================================================

const form = document.getElementById("form-recherche");
const champ = document.getElementById("champ");
const scope = document.getElementById("scope");

// Active le choix "index / texte" seulement en mode RegEx
for (const radio of document.querySelectorAll('input[name="mode"]')) {
  radio.addEventListener("change", () => {
    scope.disabled = (radio.value !== "regex" || !radio.checked);
  });
}

form.addEventListener("submit", async (evenement) => {
  evenement.preventDefault(); // empêche le rechargement de la page

  const texte = champ.value.trim();
  const mode = document.querySelector('input[name="mode"]:checked').value;

  // Construction de l'URL selon le contrat d'API
  let chemin;
  if (mode === "keyword") {
    chemin = "/search?q=" + encodeURIComponent(texte);
  } else {
    chemin = "/search/advanced?regex=" + encodeURIComponent(texte) + "&scope=" + scope.value;
  }

  const donnees = await api(chemin);

  if (donnees.error) {
    document.getElementById("message-erreur").textContent = donnees.message;
    afficher("vue-erreur");
  } else if (donnees.results.length === 0) {
    document.getElementById("message-erreur").textContent = "Aucun livre ne contient « " + texte + " ».";
    afficher("vue-erreur");
  } else {
    afficherResultats(donnees);
  } 
});

function afficherResultats(donnees) {
  document.getElementById("infos").textContent =
    donnees.total + " livre(s) trouvé(s) en " + donnees.time_ms + " ms";

  // Liste classée
  const liste = document.getElementById("liste-resultats");
  liste.innerHTML = "";
  for (const livre of donnees.results) {
    liste.innerHTML += `
      <li>
        <button type="button" class="carte" data-id="${livre.id}">
          <strong>${echapper(livre.title)}</strong> - ${echapper(livre.author)}
          <small>${livre.occurrences} occurrences · score ${livre.score}</small>
        </button>
      </li>`;
  }

  // Suggestions
  const sugg = document.getElementById("liste-suggestions");
  sugg.innerHTML = "";
  for (const livre of donnees.suggestions) {
    sugg.innerHTML += `
      <li>
        <button type="button" class="carte" data-id="${livre.id}">
          ${echapper(livre.title)}
          <small>distance ${livre.distance}</small>
        </button>
      </li>`;
  }

  afficher("vue-resultats");
}


// ============================================================
// 5. DÉTAIL D'UN LIVRE
// ============================================================

// Un seul écouteur pour tous les boutons .carte de la page
document.addEventListener("click", async (evenement) => {
  const bouton = evenement.target.closest(".carte");
  if (!bouton) return;

  const livre = await api("/books/" + bouton.dataset.id);

  document.getElementById("detail-livre").innerHTML = `
    <h2>${echapper(livre.title)}</h2>
    <p>${echapper(livre.author)} · ${livre.word_count} mots · PageRank ${livre.pagerank}</p>
    <h3>Livres proches</h3>
    <ul>
      ${livre.neighbors.map(v => `<li>${echapper(v.title)} (distance ${v.distance})</li>`).join("")}
    </ul>`;

  afficher("vue-livre");
});

document.getElementById("retour").addEventListener("click", () => afficher("vue-resultats"));
