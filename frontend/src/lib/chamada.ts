"use client";

import { urlApi } from "./api";

/* A chamada de voz entre advogado e cliente, do lado do navegador.
 *
 * O áudio vai direto de um navegador para o outro (P2P). O servidor só
 * apresenta os dois — ver `app/chamada.py`. Aqui moram as três coisas que o
 * navegador precisa fazer: pegar o microfone, montar a RTCPeerConnection e
 * conversar com a sinalização.
 *
 * Duas decisões que evitam a parte mais escorregadia do WebRTC:
 *
 * 1. **Só o advogado oferta.** O cliente nunca cria oferta, apenas responde.
 *    Isso elimina o "glare" — as duas pontas ofertando ao mesmo tempo, cada uma
 *    recusando a da outra — sem precisar do protocolo de negociação educada.
 * 2. **Candidato ICE que chega adiantado espera.** O ICE do outro lado costuma
 *    chegar antes da descrição remota estar aplicada; `addIceCandidate` nessa
 *    hora explode, então guardamos numa fila e drenamos depois.
 *
 * O que a faixa remota entrega é a voz do OUTRO — é ela que vai para a
 * transcrição no lado do advogado, e é isso que dispensa diarização.
 */

export type PapelChamada = "advogado" | "cliente";

export type EstadoChamada =
  /** Sem chamada. */
  | "fora"
  /** Na sala, esperando o outro lado aparecer. */
  | "aguardando"
  /** Os dois estão na sala; o par ainda está se estabelecendo. */
  | "conectando"
  /** Áudio fluindo. */
  | "falando"
  /** Caiu ou o outro desligou. */
  | "encerrada";

export interface EventosChamada {
  onEstado?: (estado: EstadoChamada) => void;
  /** A voz do outro lado. No advogado, é o que alimenta o Whisper. */
  onFaixaRemota?: (trilha: MediaStreamTrack) => void;
  onErro?: (mensagem: string) => void;
}

/** Usado só se `/api/chamada/config` não responder — sem STUN nenhum, a chamada
 * só fecha entre máquinas da mesma rede. */
const ICE_PADRAO: RTCIceServer[] = [{ urls: "stun:stun.l.google.com:19302" }];

/* O microfone da chamada, ao contrário do da entrevista gravada localmente,
 * LIGA o cancelamento de eco.
 *
 * Em `lib/transcricao.ts` ele está desligado, e por um bom motivo: lá o mesmo
 * microfone captava as duas vozes (entrevista no viva-voz), e o cancelador
 * trataria a voz do cliente saindo do alto-falante como eco, apagando-a.
 * Aqui cada voz tem sua própria faixa — o que volta pelo alto-falante é
 * genuinamente eco, e sem cancelar ele vira microfonia na chamada.
 *
 * `noiseSuppression` e `autoGainControl` seguem desligados: deformam a fala e
 * pioram o que o Whisper entende do outro lado. */
const AUDIO_CHAMADA: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: false,
  autoGainControl: false,
};

const INTERVALO_BATIDA_MS = 25_000;

async function servidoresIce(): Promise<RTCIceServer[]> {
  try {
    const r = await fetch(urlApi("/api/chamada/config"));
    if (!r.ok) throw new Error(String(r.status));
    const config = (await r.json()) as { iceServers?: RTCIceServer[] };
    return config.iceServers?.length ? config.iceServers : ICE_PADRAO;
  } catch {
    return ICE_PADRAO;
  }
}

export class ChamadaVoz {
  private pc: RTCPeerConnection | null = null;
  private ws: WebSocket | null = null;
  private local: MediaStream | null = null;
  private alto: HTMLAudioElement | null = null;
  private ice: RTCIceServer[] = ICE_PADRAO;
  /** Candidatos que chegaram antes da descrição remota. */
  private pendentes: RTCIceCandidateInit[] = [];
  private temDescricaoRemota = false;
  private batida: number | null = null;
  private estadoAtual: EstadoChamada = "fora";
  /** Desligamento pedido por nós — silencia o aviso de queda. */
  private desligando = false;

  constructor(
    private papel: PapelChamada,
    private eventos: EventosChamada = {},
  ) {}

  get estado(): EstadoChamada {
    return this.estadoAtual;
  }

  get mudo(): boolean {
    const t = this.local?.getAudioTracks()[0];
    return t ? !t.enabled : false;
  }

  /** Abre o microfone e entra na sala. `sala` é o token do portal do caso. */
  async entrar(sala: string): Promise<void> {
    if (this.pc) return;
    this.desligando = false;

    // getUserMedia só existe em contexto seguro: https ou localhost. Num IP de
    // rede local sem TLS o navegador nem expõe `mediaDevices`, e a mensagem
    // padrão ("undefined") não ajuda ninguém.
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(
        "O navegador só libera o microfone em conexão segura (https) ou em localhost.",
      );
    }

    this.local = await navigator.mediaDevices.getUserMedia({ audio: AUDIO_CHAMADA });
    this.ice = await servidoresIce();
    this.montarPar();
    await this.conectarSinalizacao(sala);
  }

  /** Corta o próprio microfone sem sair da chamada. Devolve o estado novo. */
  alternarMudo(): boolean {
    const trilha = this.local?.getAudioTracks()[0];
    if (!trilha) return false;
    trilha.enabled = !trilha.enabled;
    return !trilha.enabled;
  }

  desligar(): void {
    this.desligando = true;
    this.sinalizar({ type: "encerrar" });

    if (this.batida !== null) {
      clearInterval(this.batida);
      this.batida = null;
    }
    this.ws?.close();
    this.ws = null;

    this.fecharPar();

    this.local?.getTracks().forEach((t) => t.stop());
    this.local = null;

    if (this.alto) {
      this.alto.pause();
      this.alto.srcObject = null;
      this.alto = null;
    }
    this.mudarEstado("fora");
  }

  // ------------------------------------------------------------- par P2P

  private montarPar(): void {
    const pc = new RTCPeerConnection({ iceServers: this.ice });
    this.pc = pc;
    this.temDescricaoRemota = false;
    this.pendentes = [];

    // As faixas entram ANTES de qualquer oferta, então não precisamos de
    // `onnegotiationneeded`: a primeira oferta já descreve tudo o que existe.
    for (const trilha of this.local?.getAudioTracks() ?? []) {
      pc.addTrack(trilha, this.local as MediaStream);
    }

    pc.ontrack = (e) => this.receberFaixa(e.track, e.streams[0]);

    pc.onicecandidate = (e) => {
      if (e.candidate) this.sinalizar({ type: "ice", candidate: e.candidate.toJSON() });
    };

    pc.onconnectionstatechange = () => {
      if (pc !== this.pc) return; // par velho terminando de morrer
      if (pc.connectionState === "connected") this.mudarEstado("falando");
      else if (pc.connectionState === "failed") {
        // Quase sempre é NAT que o STUN não venceu — daí a falta do TURN.
        this.mudarEstado("encerrada");
        this.eventos.onErro?.(
          "Não foi possível estabelecer o áudio. Tente outra rede (4G ou Wi-Fi de casa).",
        );
      } else if (pc.connectionState === "disconnected") {
        this.mudarEstado("conectando");
      }
    };
  }

  private fecharPar(): void {
    const pc = this.pc;
    this.pc = null;
    if (!pc) return;
    pc.ontrack = null;
    pc.onicecandidate = null;
    pc.onconnectionstatechange = null;
    pc.close();
  }

  private receberFaixa(trilha: MediaStreamTrack, stream?: MediaStream): void {
    const remoto = stream ?? new MediaStream([trilha]);

    /* Este <audio> não serve só para o advogado ouvir o cliente: no Chrome, uma
     * faixa remota que não está ligada a um elemento de mídia não alimenta o
     * WebAudio — `createMediaStreamSource` devolve silêncio e a transcrição
     * sairia vazia sem erro nenhum. Manter a referência viva é parte da
     * solução; deixar o elemento ser coletado devolve o silêncio. */
    const alto = this.alto ?? new Audio();
    alto.autoplay = true;
    alto.srcObject = remoto;
    this.alto = alto;
    void alto.play().catch(() => {
      this.eventos.onErro?.("Toque na tela para liberar o áudio da chamada.");
    });

    this.eventos.onFaixaRemota?.(trilha);
  }

  // ------------------------------------------------------- sinalização

  private conectarSinalizacao(sala: string): Promise<void> {
    const url = urlApi(
      `/ws/chamada/${encodeURIComponent(sala)}?papel=${this.papel}`,
    ).replace(/^http/, "ws");

    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onmessage = (e) => {
      void this.receberSinal(JSON.parse(e.data as string));
    };
    ws.onclose = () => {
      if (this.desligando || ws !== this.ws) return;
      this.mudarEstado("encerrada");
      this.eventos.onErro?.("A conexão com a sala caiu. Entre de novo para retomar.");
    };

    return new Promise<void>((ok, falhou) => {
      ws.onopen = () => {
        this.mudarEstado("aguardando");
        // Alguns proxies fecham WebSocket ocioso em 60s. A sinalização fica
        // parada o tempo todo depois que o par fecha — o ping a mantém viva
        // para o caso de o outro lado reconectar no meio da conversa.
        this.batida = window.setInterval(
          () => this.sinalizar({ type: "ping" }),
          INTERVALO_BATIDA_MS,
        );
        ok();
      };
      ws.onerror = () => falhou(new Error("Não foi possível abrir a sala da chamada."));
      setTimeout(
        () => falhou(new Error("O servidor da chamada não respondeu.")),
        10_000,
      );
    });
  }

  private sinalizar(mensagem: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(mensagem));
  }

  private async receberSinal(m: Record<string, any>): Promise<void> {
    switch (m.type) {
      // Entramos e o outro já estava aqui.
      case "entrou":
        if (m.outroPresente) await this.ofertar();
        break;

      // O outro acabou de chegar.
      case "pronto":
        await this.ofertar();
        break;

      case "offer":
        await this.responder(m.sdp as RTCSessionDescriptionInit);
        break;

      case "answer":
        if (!this.pc || this.pc.signalingState !== "have-local-offer") break;
        await this.pc.setRemoteDescription(m.sdp as RTCSessionDescriptionInit);
        await this.drenarIce();
        break;

      case "ice":
        await this.receberIce(m.candidate as RTCIceCandidateInit | null);
        break;

      // O outro lado saiu: o par atual não serve mais. Um novo, limpo, deixa a
      // sala pronta para quando ele voltar — celular que recarrega a página é
      // o caso comum, e reaproveitar o par morto exigiria reinício de ICE.
      case "saiu":
      case "encerrar":
        this.fecharPar();
        this.montarPar();
        this.mudarEstado("aguardando");
        break;

      // Mandamos algo e não havia ninguém para receber.
      case "ausente":
        this.mudarEstado("aguardando");
        break;
    }
  }

  private async ofertar(): Promise<void> {
    // Só o advogado oferta. Ver o cabeçalho: é o que impede o glare.
    if (this.papel !== "advogado" || !this.pc) return;
    if (this.pc.signalingState !== "stable") return;
    this.mudarEstado("conectando");
    const oferta = await this.pc.createOffer();
    await this.pc.setLocalDescription(oferta);
    this.sinalizar({ type: "offer", sdp: this.pc.localDescription });
  }

  private async responder(sdp: RTCSessionDescriptionInit): Promise<void> {
    if (!this.pc) return;
    this.mudarEstado("conectando");
    await this.pc.setRemoteDescription(sdp);
    await this.drenarIce();
    const resposta = await this.pc.createAnswer();
    await this.pc.setLocalDescription(resposta);
    this.sinalizar({ type: "answer", sdp: this.pc.localDescription });
  }

  private async receberIce(candidato: RTCIceCandidateInit | null): Promise<void> {
    if (!candidato || !this.pc) return;
    if (!this.temDescricaoRemota) {
      this.pendentes.push(candidato);
      return;
    }
    // Candidato inválido não derruba a chamada: o ICE tenta outros caminhos.
    await this.pc.addIceCandidate(candidato).catch(() => {});
  }

  private async drenarIce(): Promise<void> {
    this.temDescricaoRemota = true;
    const fila = this.pendentes;
    this.pendentes = [];
    for (const c of fila) await this.pc?.addIceCandidate(c).catch(() => {});
  }

  private mudarEstado(novo: EstadoChamada): void {
    if (novo === this.estadoAtual) return;
    this.estadoAtual = novo;
    this.eventos.onEstado?.(novo);
  }
}
