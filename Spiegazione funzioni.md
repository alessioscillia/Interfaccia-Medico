@st.cache\_resource fa in modo che il risultato della funzione get\_drive() venga memorizzato dopo la prima esecuzione in una cache, così che le chiamate successive con gli stessi parametri restituiscano molto più velocemente il risultato già calcolato, senza dover ripetere l'autenticazione, essendo un'operazione lunga. 



**get\_drive()**

Dopodiché, nella funzione get\_drive() viene definito gauth = GoogleAuth(), creando così il gestore dell'autenticazione per collegarsi a Google Drive.



Dopodiché l'applicazione controlla se la chiave di sicurezza ("gcp\_service\_account") è presente nei segreti in Streamlit Cloud. Nel caso in cui lo sia, prende questa info e la mette in un dizionario e la scrive temporaneamente su un file temp\_service\_account.json. Successivamente vengono definite le variabili service\_account\_file e client\_email che contengono la chiave JSON e l'indirizzo email associato al service account. 



In alternativa, se le credenziali del service account sono su un file (service-account.json) scaricato dalla Google Cloud Console (quindi in locale), apre il suo contenuto ed estrae l'email associata al service account. 



Dopodiché, con gauth.settings\['client\_config\_backend'] = 'service' viene impostato il metodo di autenticazione su "service account", ovvero si sta dicendo a PyDrive2 di usare l'autenticazione di service account e non di una account utente. Dopodiché, viene preparato il sistema a usare il percorso del file JSON con le credenziali scaricate da Google Cloud e le email del service account per accedere alle API di Google Drive (gauth.settings\['service\_config'] = {

&nbsp;   'client\_json\_file\_path': service\_account\_file,

&nbsp;   'client\_user\_email': client\_email,  # Questo campo è richiesto da PyDrive2

})



Infine, facendo gauth.ServiceAuth() viene eseguita effettivamente l'autenticazione. PyDrive2 si collega a Google (tramite le API) e ottiene un "token", cioè un lasciapassare digitale per accedere a Drive con i permessi previsti dal suo service account.



Viene così creato un oggetto drive, che permetterà di agire direttamente su Google Drive d'ora in avanti, dal momento che è stato consentito l'accesso. 



**get\_image\_bytes\_by\_id**

Questa funzione serve a scaricare da GoogleDrive l'immagine corrispondente a un certo ID e restituirne i "bytes". In questa forma è possibile caricare l'immagine direttamente con PIL o altre librerie Python. 

La decorazione @st.cache\_data dice a Streamlit di memorizzare il risultato della funzione per quello specifico file\_id, in modo tale che se richiedi la stessa immagine più di una volta (magari passando avanti e indietro), il download da Google Drive avviene solo la prima volta. Dopodiché verrà usata la copia già scaricata, velocizzando l'app e risparmiando sia connessione a Drive che tempo. 



**load\_all\_images\_from\_drive**

Questa funzione prende la ID di una cartella principale su Google Drive, recupera ciascuna sottocartella e per ogni sottocartella trova le immagini al suo interno. Dopodiché, produce un dizionario che raggruppa i metadati (ID, titolo, nome cartella) di ogni immagine. 

In particolare @st.cache\_data(show\_spinner="Caricamento immagini da Google Drive...", ttl=3600) dice a Streamlit di memorizzare il risultato della funzione per 1 ora, in modo da non far avvenire il caricamento ogni volta che la pagina viene aggiornata. 

Dopodiché la funzione cerca le sottocartelle e ottiene una ista di oggetti che rappresentano tutte le cartelle che contengono immagini. Dopodiché, per ogni cartella ottiene la lista delle immagini che ci sono in quella cartella. 

Per ogni immagine di ciascuna cartella salva un piccolo dizionario con:

* ID e titolo immagine
* nome della sua cartella

infine viene restituito il dizionario. 



**get\_user\_images**

La funzione decide quali immagini mostrare a ogni utente, in modo che:

* Ogni utente veda solo un sottoinsieme di immagini, non tutte
* il gruppo di immagini mostrate sia diverso per ogni “gruppo” di utenti, e varia secondo un “giro” (ogni 3 utenti si passa a un nuovo gruppo).



