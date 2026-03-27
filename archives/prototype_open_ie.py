import ollama
from pydantic import BaseModel, Field, model_validator
import json
import math

# =========================================================================
# ÉTAPE 3 : L'ANCRAGE VECTORIEL (ENTITY RESOLUTION)
# =========================================================================
# Implémentation pure Python (0 dépendance) pour l'ancrage via Ollama Embeddings.

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot = sum(x*y for x, y in zip(v1, v2))
    return dot / (math.sqrt(sum(x*x for x in v1)) * math.sqrt(sum(x*x for x in v2)))

class VectorAnchor:
    def __init__(self, embed_model='nomic-embed-text'):
        self.model = embed_model
        self.ontology_vectors = {}
        
    def index_ontology(self, concepts: list):
        print(f"-> [Ancrage Vectoriel] Indexation mathématique de {len(concepts)} concepts de la T-Box...")
        for c in concepts:
            try:
                res = ollama.embeddings(model=self.model, prompt=c)
                self.ontology_vectors[c] = res['embedding']
            except Exception as e:
                print(f"   [ERREUR Embedding] Avez-vous exécuté 'ollama pull {self.model}' ?\n   Détail: {e}")
                return
                
    def resolve(self, raw_entity: str, threshold: float = 0.70):
        """Calcule le cosinus du vecteur entrant face aux vecteurs connus de l'ontologie."""
        if not self.ontology_vectors: return raw_entity, 0.0
            
        try:
            res = ollama.embeddings(model=self.model, prompt=raw_entity)
            emb = res['embedding']
            best_score = -1.0
            best_match = raw_entity
            for concept, ref_emb in self.ontology_vectors.items():
                score = cosine_similarity(emb, ref_emb)
                if score > best_score:
                    best_score = score
                    best_match = concept
            # Si le score dépasse notre seuil de sécurité, on écrase l'hallucination par le concept T-Box !
            if best_score >= threshold:
                return best_match, best_score
            return raw_entity, best_score
        except Exception:
            return raw_entity, 0.0


# =========================================================================
# ÉTAPE 5 : LE MUR DE VALIDATION (PYDANTIC = L'équivalent Python de ZOD)
# =========================================================================
# Ce modèle force l'IA à utiliser cette structure exacte, 
# et valide/rejette la donnée avant même d'attaquer la CMDB (Neo4j).

class Triplet(BaseModel):
    sujet: str = Field(description="L'entité source de la relation (ex: 'Abdelaziz Joudar')")
    predicat: str = Field(description="Le verbe d'action (si possible issu de l'ontologie, sinon improvisé par l'IA)")
    objet: str = Field(description="L'entité cible de la relation (Concept, Auteur, etc.)")
    statut_validation: str = Field(default="validé", description="Flag interne (ne pas générer)")
    
    @model_validator(mode='after')
    def flag_unrecognized_predicates(self) -> 'Triplet':
        """
        Garde l'approche Open IE souple : au lieu de crasher (Hard-Fail), 
        on flagge le triplet pour une révision humaine a posteriori (Soft-Fail).
        Sauf si c'est explicitement dans la blacklist (Hard-Fail pour rejet pur).
        """
        autorises = ['mentionne', 'a_écrit', 'co-écrit', 'utilise', 'est_défini_comme', 'impacte']
        interdits = ['détaille', 'concerne', 'a_pour_sujet']
        
        pred = self.predicat.lower()
        if pred in interdits:
            # HARD FAIL : Rejet total par Zod/Pydantic
            raise ValueError(f"Le prédicat '{pred}' est blacklisté car sa valeur sémantique est trop faible.")
            
        if pred not in autorises:
            self.statut_validation = "à_réviser" # SOFT FAIL : Human in the loop
        else:
            self.statut_validation = "validé"
            
        self.predicat = pred
        return self

class OpenIEMining(BaseModel):
    mots_cles: list[str] = Field(description="Les 3 concepts les plus lourds (Ancrés au vocabulaire si possible)")
    triplets: list[Triplet] = Field(description="La liste complète des relations du Graphe")

# =========================================================================
# ÉTAPE 4 : EXTRACTION CADRÉE (RÉSOLUTION ET RAISONNEMENT)
# =========================================================================

def extract_knowledge(texte: str, ontologie_pertinente: list, predicats_existants: list, predicats_interdits: list):
    print("-> Lancement du Raisonneur lourd (Extraction Cadrée Qwen2.5)...")
    
    # On enferme physiquement l'IA avec le schéma Zod/Pydantic
    schema_json = OpenIEMining.model_json_schema()
    
    prompt = f"""Tu es un agent expert en Ontology Mining.
Analyse le texte suivant et extrais les triplets (Sujet, Prédicat, Objet).
Consigne 1 : Pour le verbe d'action (Prédicat), essaie de converger vers ces prédicats connus : {predicats_existants}. 
Cependant, si l'action est vraiment singulière, tu es autorisé à inventer de NOUVEAUX verbes TRES PRECIS (ex: 'améliore', 'finance').
Consigne 2 : Tu as l'INTERDICTION formelle d'utiliser les verbes faibles suivants (blacklist) : {predicats_interdits}.
Consigne 3 : Pour l'Objet, essaie de relier cela à l'ontologie suivante : {ontologie_pertinente}

Texte :
{texte}
"""
    
    try:
        # L'API Ollama récente gère le paramètre "format" avec un JSON Schema !
        response = ollama.chat(
            model='qwen2.5:7b-instruct-q4_K_M',
            messages=[{'role': 'user', 'content': prompt}],
            format=schema_json, # LA MAGIE EST ICI
            options={'num_ctx': 4096}
        )
        
        # Le mur de parsing (comme .safeParse(jsonStr) de Zod)
        raw_json_str = response['message']['content']
        print(f"\n[DEBUG] JSON Brut reçu de l'IA :\n{raw_json_str}\n")
        
        validated_data = OpenIEMining.model_validate_json(raw_json_str)
        return validated_data
        
    except Exception as e:
        print(f"!!! ÉCHEC DU MUR DE VALIDATION (ZOD/PYDANTIC) : {e}")
        # Ici dans un flux réel, l'Orchestrateur relance le LLM avec le message d'erreur pour qu'il se corrige
        return None

# =========================================================================
# TEST DU PIPELINE (Macro)
# =========================================================================
if __name__ == "__main__":
    fragment_test = "Dans cet article de 2024, Abdelaziz Joudar détaille comment l'entreprise utilise l'IA Générative pour améliorer la Threat Modeling face à la cybercriminalité."
    
    # Simulation de l'Étape 2 (Routage Ontologique) : 
    # Le modèle A (Classification) a détecté 'Sécurité' et on n'a chargé en RAM que ce sous-graphe :
    t_box_restreinte = ['Generative AI', 'Large Language Models (LLM)', 'Cybercriminalité', 'Malware Protection', 'Threat Modeling']
    predicats_connus = ['mentionne', 'a_écrit', 'co-écrit', 'utilise', 'est_défini_comme']
    predicats_bannis = ['détaille', 'concerne', 'impacte', 'a_pour_sujet']
    
    # --- PHASE A : ÉTAPE 3 (Ancrage Mathématique) ---
    anchor_engine = VectorAnchor(embed_model='nomic-embed-text')
    anchor_engine.index_ontology(t_box_restreinte)
    
    # --- PHASE B : ÉTAPE 4 & 5 (Extraction Cadrée Qwen2.5 + Validation Pydantic) ---
    resultat = extract_knowledge(fragment_test, t_box_restreinte, predicats_connus, predicats_bannis)
    
    if resultat:
        print("\n====== RÉSULTAT ZOD/PYDANTIC VALIDÉ ======")
        print(f"Mots-clés bruts de l'IA : {resultat.mots_cles}")
        print("\n[VUE 1] Les Triplets Bruts (Avant résolution d'entités) :")
        for t in resultat.triplets:
            if t.statut_validation == "à_réviser":
                print(f"  - ⚠️ [À RÉVISER] [{t.sujet}] --({t.predicat})--> [{t.objet}]")
            else:
                print(f"  - ✅ [OK] [{t.sujet}] --({t.predicat})--> [{t.objet}]")
                
        # --- PHASE C : LA PURGE NÉO4J (Nettoyage avant base de données) ---
        print("\n====== RÉSULTAT FINAL (APRÈS ANCRAGE VECTORIEL) ======")
        print("Voici ce qui ira RÉELLEMENT dans Neo4j (Fusion des hallucinations) :")
        for t in resultat.triplets:
            # On passe le Sujet et l'Objet dans le crible de Similarité Cosinus
            clean_sujet, score_s = anchor_engine.resolve(t.sujet, threshold=0.75)
            clean_objet, score_o = anchor_engine.resolve(t.objet, threshold=0.75)
            
            str_s = f"[{t.sujet}]" if clean_sujet == t.sujet else f"[{clean_sujet}] (⬅️ Remplacé par le vecteur T-Box à {score_s*100:.0f}%)"
            str_o = f"[{t.objet}]" if clean_objet == t.objet else f"[{clean_objet}] (⬅️ Remplacé par le vecteur T-Box à {score_o*100:.0f}%)"
            
            print(f"  - {str_s} \n        --({t.predicat})--> \n        {str_o}\n")
    else:
        print("La donnée ne touchera jamais Neo4j (Pipeline protégé).")
