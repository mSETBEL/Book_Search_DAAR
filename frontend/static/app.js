
// accès serveur 
async function api(chemin) {
   try {
    const reponse = await fetch("/api" + chemin);
    const corps = await reponse.json();
    if (reponse.ok) return corps;
    return { error: true, message: corps.message || "Erreur du serveur (" + reponse.status + ")" };
  } catch (e) {
    return { error: true, message: "Impossible de joindre le serveur." };
  }
}

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
