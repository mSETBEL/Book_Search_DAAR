
// accès serveur 
async function api(chemin) {
    const reponse = await fetch("/api" + chemin);
    if (reponse.status === 401) {          // session absente ou expirée : retour à la page de connexion
        window.location.replace("/login.html");
        return { error: "unauthorized", message: "Connexion requise." };
    }
    return await reponse.json();
}

// ===== AUTHENTIFICATION =====
// La page reste invisible (classe auth-pending) tant que la session n'est pas confirmée.
(async function verifierSession() {
  try {
    const reponse = await fetch("/api/auth/me");
    if (!reponse.ok) { window.location.replace("/login.html"); return; }
    const utilisateur = await reponse.json();
    document.getElementById("nom-utilisateur").textContent = utilisateur.username;
    document.documentElement.classList.remove("auth-pending");
  } catch (e) {
    window.location.replace("/login.html");
  }
})();

document.getElementById("btn-deconnexion").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => { });
  window.location.replace("/login.html");
});

// Affiche une seule vue et cache les autres
function afficher(idVue) {
  const vues = ["vue-accueil", "vue-resultats", "vue-livre", "vue-erreur", "vue-texte"];
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
          <strong>${echapper(livre.title)}</strong> - ${echapper(livre.author || "Auteur inconnu")}
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

let livreCourant = null;

// Un seul écouteur pour tous les boutons .carte de la page
document.addEventListener("click", async (evenement) => {
  const bouton = evenement.target.closest(".carte");
  if (!bouton) return;

  // Compte la consultation pour les clics
  fetch("/api/books/" + bouton.dataset.id + "/click", { method: "POST" }).catch(() => { });

  const livre = await api("/books/" + bouton.dataset.id);

  livreCourant = livre;

  // Affiche les détails du livre
  document.getElementById("detail-livre").innerHTML = `
    <h1>${echapper(livre.title)} · ${echapper(livre.author || "Auteur inconnu")} </h1>
    <p>${livre.word_count} mots · PageRank ${livre.pagerank}</p>
    <h3>Livres proches</h3>
    <ul>
      ${livre.neighbors.map(v => `<li>${echapper(v.title)} (distance ${v.distance})</li>`).join("")}
    </ul>`;

  afficher("vue-livre");
});

// ecouteur pour le bouton "Retour aux résultats"
document.getElementById("retour").addEventListener("click", () => afficher("vue-resultats"));

// ecouteur pour le bouton "Lire le livre"
document.getElementById("btn-lire").addEventListener("click", async () => {
  const donnees = await api("/books/" + livreCourant.id + "/text");
  document.getElementById("titre-texte").textContent = livreCourant.title;
  document.getElementById("texte-livre").textContent = donnees.text;
  afficher("vue-texte");
  window.scrollTo(0, 0);
});

// ecouteur pour le bouton "Retour vers la fiche du livre"
document.getElementById("retour-texte").addEventListener("click", () => afficher("vue-livre"));


// LIVRES POPULAIRES (page d'accueil)
async function chargerPopulaires() {
  const liste = document.getElementById("liste-populaires");
  const aucun = document.getElementById("aucun-populaire");

  const donnees = await api("/popular");
  const livres = donnees.results || [];   // en cas d'erreur du serveur : liste vide

  liste.innerHTML = "";
  aucun.hidden = livres.length > 0;       // message affiché seulement si la liste est vide

  for (const livre of livres) {
    liste.innerHTML += `
      <li>
        <button type="button" class="carte" data-id="${livre.id}">
          <strong>${echapper(livre.title)}</strong> - ${echapper(livre.author || "Auteur inconnu")}
          <small>${livre.nb_clic} consultation(s)</small>
        </button>
      </li>`;
  }
}

// RETOUR À L'ACCUEIL (clic sur le titre)

document.getElementById("lien-accueil").addEventListener("click", (evenement) => {
  evenement.preventDefault(); // pas de rechargement complet de la page
  champ.value = "";
  afficher("vue-accueil");
  chargerPopulaires(); // la liste tient compte des derniers clics
});

// Remplir liste au chargement de la page
chargerPopulaires();