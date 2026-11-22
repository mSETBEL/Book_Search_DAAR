// Page de connexion / inscription

const message = document.getElementById("message");
const formConnexion = document.getElementById("form-connexion");
const formInscription = document.getElementById("form-inscription");
const ongletConnexion = document.getElementById("onglet-connexion");
const ongletInscription = document.getElementById("onglet-inscription");

function montrer(texte, info = false) {
  message.textContent = texte;
  message.classList.toggle("info", info);
  message.hidden = !texte;
}

// Déjà connecté ? on va directement à l'application
fetch("/api/auth/me").then((r) => { if (r.ok) window.location.replace("/"); }).catch(() => { });

// L'inscription est-elle ouverte ?
fetch("/api/auth/config").then((r) => r.json()).then((c) => {
  if (!c.registration_open) ongletInscription.hidden = true;
}).catch(() => { });

function choisirOnglet(connexion) {
  formConnexion.hidden = !connexion;
  formInscription.hidden = connexion;
  ongletConnexion.classList.toggle("actif", connexion);
  ongletInscription.classList.toggle("actif", !connexion);
  ongletConnexion.setAttribute("aria-selected", connexion);
  ongletInscription.setAttribute("aria-selected", !connexion);
  montrer("");
  // curseur dans le premier champ du formulaire affiché
  (connexion ? formConnexion : formInscription).querySelector("input").focus();
}
ongletConnexion.addEventListener("click", () => choisirOnglet(true));
ongletInscription.addEventListener("click", () => choisirOnglet(false));

// Une case "Afficher le mot de passe" dans chaque formulaire
const casesMdp = document.querySelectorAll(".case-mdp");
for (const caseMdp of casesMdp) {
  caseMdp.addEventListener("change", () => {
    for (const champ of document.querySelectorAll("input[name^='password']")) {
      champ.type = caseMdp.checked ? "text" : "password";
    }
    // Les deux cases restent dans le même état, quel que soit l'onglet
    for (const autre of casesMdp) autre.checked = caseMdp.checked;
  });
}

// Envoie les identifiants ; en cas de succès le serveur pose le cookie de session
async function envoyer(chemin, username, password, bouton) {
  bouton.disabled = true;
  try {
    const reponse = await fetch("/api/auth/" + chemin, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const donnees = await reponse.json().catch(() => ({}));
    if (reponse.ok) {
      window.location.replace("/");
      return;
    }
    // erreurs de l'API : {error, message} ; erreurs de validation FastAPI : {detail: [...]}
    const detail = Array.isArray(donnees.detail) ? donnees.detail[0]?.msg : donnees.detail;
    montrer(donnees.message || detail || "Requête invalide.");
  } catch (e) {
    montrer("Serveur injoignable, réessayez.");
  } finally {
    bouton.disabled = false;
  }
}

formConnexion.addEventListener("submit", (e) => {
  e.preventDefault();
  envoyer("login", formConnexion.username.value.trim(), formConnexion.password.value,
          formConnexion.querySelector("button"));
});

formInscription.addEventListener("submit", (e) => {
  e.preventDefault();
  if (formInscription.password.value !== formInscription.password2.value) {
    montrer("Les deux mots de passe ne correspondent pas.");
    return;
  }
  envoyer("register", formInscription.username.value.trim(), formInscription.password.value,
          formInscription.querySelector("button"));
});
