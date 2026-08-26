# compound-exposure — sintesi in italiano

*Il repository è in inglese. Questa pagina è un riassunto per chi arriva dal
mercato italiano; per il metodo completo vedere [README.md](README.md).*

## Il problema

La maggior parte dei programmi di security awareness viene erogata in modo
uniforme su tutta la popolazione, misura la frequenza dei corsi invece del
comportamento, e non è in grado di dire se qualcosa è cambiato. Il budget
finisce distribuito equamente tra persone che non sono il problema.

## La proposta

Un metodo che combina il **rischio umano** (dati di simulazione
phishing e formazione, famiglia KnowBe4) con il **rischio tecnico** (dati di
vulnerability management, famiglia Qualys VMDR) in un'unica classifica di
**esposizione composta** (Compound Exposure Score, da cui il nome) per unità
organizzativa, con un'implementazione funzionante che
produce un report direzionale.

Tre indici, tutti da 0 a 100, dove più alto significa peggio:

- **HRI** — indice di rischio umano: suscettibilità, resilienza, gap formativo
- **TRI** — indice di rischio tecnico: gravità pesata per criticità sul quartile
  peggiore degli asset, più latenza di remediation
- **CES** — esposizione composta, media geometrica dei due vettori, corretta per
  la confidenza del dato

## Le due scelte di progetto che contano

**Il tasso di segnalazione pesa quanto il tasso di click, con segno opposto.**
Un click genera un incidente che qualcuno deve scoprire; una segnalazione
genera un incidente già scoperto, dal sensore più economico che l'azienda
possiede. Due unità che cliccano allo stesso tasso non sono nella stessa
posizione se una segnala al 30% e l'altra al 3%.

**Il dato mancante alza il punteggio, non lo abbassa mai.** Un'unità non
misurata non è un'unità senza problemi: è un'unità di cui non si sa nulla. La
correzione è un bias dichiarato, non neutrale, e serve a rendere sconveniente
togliere dal perimetro le popolazioni scomode.

## Misurazione del cambiamento nel tempo

Il documento [`docs/06-measuring-change.md`](docs/06-measuring-change.md)
affronta la domanda che un cliente pone per seconda e a cui tiene di più: *è
cambiato qualcosa?* Confrontare due tassi aggregati non basta, per quattro
ragioni — il turnover della popolazione, la difficoltà variabile della
campagna, il rumore campionario e la regressione verso la media. Il metodo usa
una coorte chiusa, un braccio di controllo ottenuto tramite rilascio scaglionato
(nessuno viene privato della formazione: le unità pianificate più tardi fanno da
controfattuale per quelle formate prima) e una stima
differenza-nelle-differenze.

Nell'esempio incluso un'unità mostra un miglioramento statisticamente
significativo che sparisce del tutto una volta considerato il braccio di
controllo: il tasso era sceso perché la seconda campagna era più facile, non
perché il programma avesse funzionato.

## Esecuzione su dati reali

Il documento [`docs/07-ingesting-real-data.md`](docs/07-ingesting-real-data.md)
copre l'applicazione a un export vero. Tre punti che il tool impone, perché
sono i modi in cui il dato reale inganna: serve un'anagrafica del personale
(l'export contiene solo chi è stato arruolato in una campagna, quindi da solo
non produce il denominatore della copertura); il denominatore è la consegna e
non la programmazione, quindi i messaggi respinti si escludono; e il
fallimento è graduato — click, allegato aperto, macro abilitata e credenziale
inserita non sono la stessa cosa.

L'indirizzo email viene sostituito da uno pseudonimo con un salt fornito
dall'ambiente, tutte le altre colonne personali vengono scartate, e i file di
mappatura per cliente sono esclusi dal versionamento.

## Rilevanza normativa

Il documento [`docs/04-nis2-article-20.md`](docs/04-nis2-article-20.md) mappa
cosa questo metodo produce come evidenza rispetto agli obblighi dell'articolo
20 NIS2 (approvazione e supervisione delle misure da parte degli organi di
gestione, formazione degli organi di gestione, formazione periodica del
personale) e all'articolo 21(2)(g), e — cosa più importante — dichiara
esplicitamente cosa **non** copre. In Italia il riferimento di recepimento è il
D.Lgs. 138/2024.

## Avvertenze

- **Tutti i dati nel repository sono inventati.** Nessun dato, risultato o
  contesto proveniente da clienti reali è presente in alcuna forma, nemmeno
  anonimizzata.
- **I pesi sono argomentati, non calibrati su dati empirici.** Non esiste un
  training set. Presentarlo come modello validato sarebbe scorretto.
- **Il punteggio serve a ordinare il lavoro**, non a misurare il rischio in
  unità confrontabili con l'esterno e non a fare benchmark tra aziende.
- I limiti noti del modello, inclusi quelli non risolti, sono in
  [`docs/05-limits.md`](docs/05-limits.md).

## Esecuzione

Python 3.9 o successivo. **Nessuna dipendenza esterna, nessun ambiente
virtuale, nessuna installazione**: i tool usano solo la libreria standard.

L'interprete si invoca in modo diverso a seconda del sistema operativo:

| Sistema | Comando |
|---------|---------|
| Linux, macOS | `python3` |
| Windows | `py` (oppure `python`) — `python3` viene intercettato dall'alias del Microsoft Store e fallisce |

I comandi qui sotto usano `python3`. Su Windows sostituire con `py`.

```bash
python3 tools/generate_synthetic_data.py --users 2000 --period P1 --outdir data/synthetic
python3 tools/compute_exposure.py --indir data/synthetic --out data/scores.json
python3 tools/build_report.py --scores data/scores.json --out examples/sample-report.md

python3 tools/generate_synthetic_data.py --users 2000 --period P2 --outdir data/synthetic-p2
python3 tools/compute_exposure.py --indir data/synthetic-p2 --out data/scores-p2.json

python3 tools/compare_periods.py
```

Il seed è fisso: ogni clone produce output identico byte per byte.
