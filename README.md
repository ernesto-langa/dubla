# Dubla

Vídeos em inglês, ouvidos e legendados em português.

```bash
dubla                      # abre o painel no navegador (arranca-o se preciso)
dubla "LINK" --nome aula08 # traduz um vídeo direto no terminal
dubla aovivo --voz         # legendas + voz PT em tempo real
dubla ajuda
```
## Instalar

Linux com PulseAudio (testado em Ubuntu 22.04). Precisa de `python3` (≥ 3.10, com `tkinter`), `ffmpeg`,
`curl` e `pulseaudio-utils`; o `uv` é opcional mas acelera a instalação.

```bash
git clone <repositório> dubla && cd dubla
./instalar.sh
```
Cria o `.venv`, instala as dependências, descarrega o modelo de tradução offline (`modelos/en_pt`) e põe o
comando `dubla` em `~/.local/bin`. Se mudares a pasta de sítio, apaga o `.venv` e corre o `./instalar.sh` de novo.

Para aulas do Whop é preciso ter sessão iniciada no Whop no Google Chrome (as cookies são lidas do Chrome, via
keyring do GNOME). Os vídeos, as traduções e os links das aulas ficam em `videos/`, que o `.gitignore` exclui:
são conteúdo dos cursos e só para uso pessoal.

## Painel (a forma mais simples)

```bash
./painel.py        # abre http://localhost:8765 no navegador
```
- colar o link da aula, escolher voz/tradutor e carregar em **Traduzir** (o nome `aulaNN` é sugerido sozinho);
- lista de aulas com estado e progresso ao vivo; **Ver** (player com legendas PT/EN), **VLC** (para trocar para o
  áudio inglês), **Transcrição** (EN e PT lado a lado, com pesquisa), **Mudar voz**, **Retomar**, **Parar**,
  **Registo**, **Pasta**, **Apagar** (pede segundo clique);
- botão para ligar/desligar as **legendas ao vivo**.

**Google Tradutor bloqueado (captcha):** o painel mostra o estado do Google no topo. Se pedir verificação,
carrega em **Abrir captcha**, resolve-o no Chrome, espera ~30 s e carrega em **Verificar outra vez**: o script
usa as cookies do Chrome, por isso aproveita a autorização. Aulas traduzidas offline ganham o botão
**Retraduzir com Google** (refaz só tradução, voz e MP4).

As traduções correm à parte: fechar o painel (Ctrl+C) ou o navegador não as interrompe.
O painel só aceita ligações deste computador.

## Em tempo real (legendas ao vivo, como no YouTube)

```bash
./legendas_ao_vivo.py
```
Abre uma faixa de legendas por cima de todas as janelas e traduz **o som que estiver a tocar no computador**
(Whop, YouTube, VLC, uma chamada…). Mostra o PT em destaque, a frase anterior em cinzento e o inglês por baixo.
As legendas aparecem enquanto a pessoa fala e ficam fixas ~2–4 s depois de a frase terminar.

- arrastar com o rato: mover · roda do rato: tamanho da letra · Esc ou duplo clique: fechar
- `--sem-ingles` esconde o texto original; `--letra 32` muda o tamanho inicial
- `--modelo small.en` é mais preciso mas atrasa mais (por omissão `base.en`)
- tudo o que é legendado fica guardado em `ao_vivo/<data>.txt`
- a transcrição e a tradução são offline (não dependem do Google)

### Com voz PT ao vivo

```bash
./legendas_ao_vivo.py --voz                      # pt-BR-AntonioNeural
./legendas_ao_vivo.py --voz pt-PT-RaquelNeural --volume-original 0.15
```
(ou no painel: escolher "+ voz …" ao lado de **Ligar**). Enquanto está ligado, o som das aplicações passa por uma
saída virtual "Traducao_EN": o inglês é captado dali e continua a ouvir-se baixinho (`--volume-original`, 25% por
omissão); a voz PT vai direta às colunas, por isso não é captada de novo. Ao desligar, tudo volta à saída normal.
A voz usa o Edge TTS (precisa de internet) e fala cada frase ~3–5 s depois do inglês; se ficar para trás, fala mais
depressa e, se preciso, salta frases antigas para não perder a sincronia.

## Dobragem completa (ficheiro MP4 com voz PT)

`traduzir.py` transforma um vídeo em inglês num MP4 com:
- áudio **dobrado em português** (faixa por omissão; o inglês original fica baixinho por baixo),
- a faixa **inglesa original**,
- legendas **PT** e **EN** (e também `.srt` soltos).

Tudo fica em `videos/<nome>/`. Se o processo for interrompido, ao correr outra vez retoma do último passo.

## Uso

```bash
./traduzir.py "URL" --nome aula02
vlc videos/aula02/aula02_PT.mp4
```

A `URL` pode ser:
- **uma página de aula Whop** (`https://whop.com/.../lessons/lesn_...`): o script usa a tua sessão do Chrome
  (o último perfil usado; muda com `--perfil-chrome "Profile 2"`) para pedir ao Whop o link do vídeo. Se `--nome`
  não for indicado, usa o título da aula;
- YouTube, Vimeo, etc. (tudo o que o `yt-dlp` suporta), diretamente;
- um ficheiro local;
- um link `.m3u8`/`.mp4` direto.

### Alternativa: atalho (bookmarklet) para copiar o link do vídeo

Útil para outros sites com player Mux. Cria um marcador no Chrome e cola isto no campo URL:

```
javascript:(()=>{const v=document.querySelector('mux-player,mux-video,video');const s=v&&(v.getAttribute('src')||v.src);if(!s||s.startsWith('blob:')){alert('Vídeo não encontrado (espera que o player carregue)');return}navigator.clipboard.writeText(s).then(()=>alert('Link do vídeo copiado'))})()
```

Abre a aula, carrega no marcador e depois corre: `./traduzir.py "<colar>" --nome aulaXX`.
O link tem um token que expira, por isso usa-o logo.

## Opções

| opção | por omissão | notas |
|---|---|---|
| `--voz` | `pt-BR-AntonioNeural` | `pt-BR-FranciscaNeural`, `pt-PT-DuarteNeural`, `pt-PT-RaquelNeural` |
| `--velocidade` | `+10%` | ritmo base da voz |
| `--modelo` | `small.en` | `base.en` (mais rápido), `medium.en` (mais preciso, mais lento) |
| `--fundo` | `0.12` | volume do inglês por baixo da dobragem; `0` para silenciar |

Para refazer só a voz (por exemplo, para mudar de voz), apaga `videos/<nome>/tts/`, `dobragem_pt.wav` e corre de novo.

## Como funciona

yt-dlp (download) → faster-whisper no CPU (transcrição com tempos por palavra, agrupada em frases) → Google Translate
(deep-translator) → Edge TTS (voz neural) → cada frase é colocada no instante em que é dita e acelerada até 1,5x se
não couber no espaço → ffmpeg junta tudo.

Precisa de internet para a tradução e a voz. Os vídeos são só para uso pessoal.
