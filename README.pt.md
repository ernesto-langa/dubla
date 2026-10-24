# Dubla

[English](README.md) · **Português**

Assiste a vídeos em inglês em português: dobragem com voz PT, legendas e tradução em tempo real.
Corre no teu computador, com Whisper.

```bash
dubla                         # abre o painel no navegador (arranca-o se preciso)
dubla "LINK" --nome aula08    # traduz um vídeo direto no terminal
dubla aovivo --voz            # legendas + voz PT em tempo real
dubla ajuda
```

## Funcionalidades

- **Dobragem completa**: transforma um vídeo num MP4 com voz em português, a faixa original em inglês e legendas PT/EN.
- **Legendas ao vivo**: traduz o som que estiver a tocar no computador (qualquer site ou aplicação), com voz PT opcional.
- **Painel web local**: gere as traduções, vê os vídeos, lê a transcrição EN/PT lado a lado.
- **Aulas do Whop**: aceita o link da página da aula e usa a tua sessão do Chrome para obter o vídeo.
- **Tradução offline**: se o Google Tradutor não estiver disponível, usa um modelo local.

## Instalar

Linux com PulseAudio (testado em Ubuntu 22.04). Precisa de `python3` (≥ 3.10, com `tkinter`), `ffmpeg`,
`curl` e `pulseaudio-utils`; o [`uv`](https://github.com/astral-sh/uv) é opcional mas acelera a instalação.

```bash
git clone https://github.com/ernesto-langa/dubla.git && cd dubla
./instalar.sh
```

O `instalar.sh` cria o `.venv`, instala as dependências, descarrega o modelo de tradução offline (`modelos/en_pt`)
e põe o comando `dubla` em `~/.local/bin`. O modelo de transcrição Whisper (~480 MB) descarrega-se sozinho na
primeira tradução. Se mudares a pasta de sítio, apaga o `.venv` e corre o `./instalar.sh` de novo.

## Painel (a forma mais simples)

```bash
dubla        # ou ./painel.py — abre http://localhost:8765
```

- cola o link da aula, escolhe a voz e o tradutor e carrega em **Traduzir** (o nome `aulaNN` é sugerido sozinho);
- lista de aulas com estado e progresso ao vivo: **Ver** (player com legendas PT/EN), **VLC** (para trocar para o
  áudio inglês), **Transcrição** (EN e PT lado a lado, com pesquisa), **Mudar voz**, **Retomar**, **Parar**,
  **Registo**, **Pasta**, **Apagar** (pede segundo clique);
- liga e desliga as **legendas ao vivo**, com ou sem voz.

**Google Tradutor bloqueado (captcha):** o painel mostra o estado do Google no topo. Se pedir verificação,
carrega em **Abrir captcha**, resolve-o no Chrome, espera ~30 s e carrega em **Verificar outra vez**: o script
usa as cookies do Chrome, por isso aproveita a autorização. Aulas traduzidas offline ganham o botão
**Retraduzir com Google** (refaz só tradução, voz e MP4).

As traduções correm à parte: fechar o painel (Ctrl+C) ou o navegador não as interrompe.
O painel só aceita ligações deste computador.

## Legendas ao vivo

```bash
dubla aovivo
```

Abre uma faixa de legendas por cima de todas as janelas e traduz **o som que estiver a tocar no computador**
(Whop, YouTube, VLC, uma chamada…). Mostra o PT em destaque, a frase anterior em cinzento e o inglês por baixo.
As legendas aparecem enquanto a pessoa fala e ficam fixas ~2–4 s depois de a frase terminar.

- arrastar com o rato: mover · roda do rato: tamanho da letra · Esc ou duplo clique: fechar
- `--sem-ingles` esconde o texto original; `--letra 32` muda o tamanho inicial
- `--modelo small.en` é mais preciso mas atrasa mais (por omissão `base.en`)
- tudo o que é legendado fica guardado em `ao_vivo/<data>.txt`
- a transcrição e a tradução são offline (não dependem do Google)

### Com voz PT

```bash
dubla aovivo --voz                                   # pt-BR-AntonioNeural
dubla aovivo --voz pt-PT-RaquelNeural --volume-original 0.15
```

Enquanto está ligado, o som das aplicações passa por uma saída virtual "Traducao_EN": o inglês é captado dali e
continua a ouvir-se baixinho (`--volume-original`, 25% por omissão); a voz PT vai direta às colunas, por isso não é
captada de novo. Ao desligar, tudo volta à saída normal.

A voz usa o Edge TTS (precisa de internet) e fala cada frase ~3–5 s depois do inglês. Se ficar para trás, fala mais
depressa e, se preciso, salta frases antigas para não perder a sincronia.

## Dobragem completa (MP4 com voz PT)

```bash
dubla "URL" --nome aula02
vlc videos/aula02/aula02_PT.mp4
```

O MP4 tem:
- áudio **dobrado em português** (faixa por omissão; o inglês original fica baixinho por baixo);
- a faixa **inglesa original**;
- legendas **PT** e **EN** (e também `.srt` soltos).

Tudo fica em `videos/<nome>/`. Se o processo for interrompido, ao correr outra vez retoma do último passo.

A `URL` pode ser:
- **uma página de aula Whop** (`https://whop.com/.../lessons/lesn_...`): o script usa a tua sessão do Chrome para
  pedir ao Whop o link do vídeo (experimenta os perfis do Chrome até encontrar um com sessão). Sem `--nome`, usa o
  título da aula;
- YouTube, Vimeo, etc. (tudo o que o `yt-dlp` suporta);
- um ficheiro local;
- um link `.m3u8`/`.mp4` direto.

### Opções

| opção | por omissão | notas |
|---|---|---|
| `--nome` | título / nome do ficheiro | pasta de saída em `videos/` |
| `--voz` | `pt-BR-AntonioNeural` | `pt-BR-FranciscaNeural`, `pt-PT-DuarteNeural`, `pt-PT-RaquelNeural` |
| `--velocidade` | `+10%` | ritmo base da voz |
| `--modelo` | `small.en` | `base.en` (mais rápido), `medium.en` (mais preciso, mais lento) |
| `--fundo` | `0.12` | volume do inglês por baixo da dobragem; `0` para silenciar |
| `--tradutor` | `google` | `google` (passa ao offline se falhar) ou `local` |
| `--perfil-chrome` | todos, começando pelo último usado | perfil do Chrome com sessão no Whop |

### Alternativa: atalho (bookmarklet) para copiar o link do vídeo

Útil para outros sites com player Mux. Cria um marcador no Chrome e cola isto no campo URL:

```
javascript:(()=>{const v=document.querySelector('mux-player,mux-video,video');const s=v&&(v.getAttribute('src')||v.src);if(!s||s.startsWith('blob:')){alert('Vídeo não encontrado (espera que o player carregue)');return}navigator.clipboard.writeText(s).then(()=>alert('Link do vídeo copiado'))})()
```

Abre a aula, carrega no marcador e depois corre `dubla "<colar>" --nome aulaXX`. O link tem um token que expira,
por isso usa-o logo.

## Como funciona

yt-dlp (download) → faster-whisper no CPU (transcrição com tempos por palavra, agrupada em frases) →
Google Tradutor (com as cookies do Chrome) ou modelo offline Argos/CTranslate2 → Edge TTS (voz neural) →
cada frase é colocada no instante em que é dita e acelerada até 1,5x se não couber → ffmpeg junta tudo.

## Testes

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt   # ou .venv/bin/pip install -r …
.venv/bin/python -m pytest
```

## Privacidade e uso

- Os vídeos, as traduções e os links das aulas ficam em `videos/`, que o `.gitignore` exclui. São conteúdo dos
  cursos: usa-os só para fins pessoais e não os partilhes.
- As cookies do Chrome são lidas localmente (via keyring do GNOME) e só são enviadas para o próprio site
  (whop.com, google.com).
- O painel só escuta em `127.0.0.1`.
