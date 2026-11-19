/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 NTWeb
 */
/**
 * @file g729.c  Codec G.729 (RFC 3551, RFC 4856) sobre a libbcg729
 *
 * O baresip 4.12.0 não traz módulo G.729. Este módulo do NT-Fone usa a libbcg729
 * (Belledonne): 10 bytes por quadro de 10 ms a 8 kHz, VAD/DTX desligado no envio.
 *
 * Pela RFC 4856 uma oferta G729 sem fmtp implica annexb=yes, então o PBX pode mandar
 * um quadro SID (2 bytes) no fim do pacote: o decoder o aceita. Nós oferecemos
 * "annexb=no" e nunca enviamos SID.
 *
 * Não define fmtp_cmph de propósito: sem ele, diferença de annexb entre as pontas
 * não marca o codec como não suportado.
 */
#include <string.h>
#include <re.h>
#include <rem_au.h>
#include <baresip.h>
#include <bcg729/encoder.h>
#include <bcg729/decoder.h>


enum {
	FRAME_SAMPC = 80,	/* amostras por quadro (10 ms a 8 kHz) */
	FRAME_BYTES = 10,	/* quadro de voz */
	SID_BYTES   = 2,	/* quadro de ruído de conforto (Anexo B) */
	PLC_FRAMES  = 2		/* 20 ms: tamanho do pacote antes de decodificar o primeiro */
};


struct auenc_state {
	bcg729EncoderChannelContextStruct *ctx;
};

struct audec_state {
	bcg729DecoderChannelContextStruct *ctx;
	size_t last_frames;	/* quadros do último pacote: quanto o PLC repõe por pacote perdido */
};


static void enc_destructor(void *arg)
{
	struct auenc_state *st = arg;

	if (st->ctx)
		closeBcg729EncoderChannel(st->ctx);
}


static void dec_destructor(void *arg)
{
	struct audec_state *st = arg;

	if (st->ctx)
		closeBcg729DecoderChannel(st->ctx);
}


static int encode_update(struct auenc_state **aesp, const struct aucodec *ac,
			 struct auenc_param *prm, const char *fmtp)
{
	struct auenc_state *st;
	(void)prm;
	(void)fmtp;

	if (!aesp || !ac)
		return EINVAL;

	if (*aesp)
		return 0;

	st = mem_zalloc(sizeof(*st), enc_destructor);
	if (!st)
		return ENOMEM;

	st->ctx = initBcg729EncoderChannel(0);  /* VAD desligado */
	if (!st->ctx) {
		mem_deref(st);
		return ENOMEM;
	}

	*aesp = st;

	return 0;
}


static int decode_update(struct audec_state **adsp, const struct aucodec *ac,
			 const char *fmtp)
{
	struct audec_state *st;
	(void)fmtp;

	if (!adsp || !ac)
		return EINVAL;

	if (*adsp)
		return 0;

	st = mem_zalloc(sizeof(*st), dec_destructor);
	if (!st)
		return ENOMEM;

	st->ctx = initBcg729DecoderChannel();
	if (!st->ctx) {
		mem_deref(st);
		return ENOMEM;
	}

	st->last_frames = PLC_FRAMES;
	*adsp = st;

	return 0;
}


static int encode(struct auenc_state *st, bool *marker, uint8_t *buf,
		  size_t *len, int fmt, const void *sampv, size_t sampc)
{
	const int16_t *in = sampv;
	size_t frames, i;
	(void)marker;

	if (!st || !buf || !len || !sampv)
		return EINVAL;

	if (fmt != AUFMT_S16LE)
		return ENOTSUP;

	if (sampc % FRAME_SAMPC)
		return EINVAL;

	frames = sampc / FRAME_SAMPC;
	if (*len < frames * FRAME_BYTES)
		return ENOMEM;

	for (i = 0; i < frames; i++) {
		uint8_t n = 0;

		bcg729Encoder(st->ctx, &in[i * FRAME_SAMPC],
			      &buf[i * FRAME_BYTES], &n);
		if (n != FRAME_BYTES)
			return EPROTO;
	}

	*len = frames * FRAME_BYTES;

	return 0;
}


/* Pacote = N quadros de 10 bytes e, no máximo, um SID de 2 bytes no fim. */
static int decode(struct audec_state *st, int fmt, void *sampv, size_t *sampc,
		  bool marker, const uint8_t *buf, size_t len)
{
	int16_t *out = sampv;
	size_t voice, frames, i;
	bool sid;
	(void)marker;

	if (!st || !sampv || !sampc || !buf)
		return EINVAL;

	if (fmt != AUFMT_S16LE)
		return ENOTSUP;

	sid = (len % FRAME_BYTES) == SID_BYTES;
	if (!len || ((len % FRAME_BYTES) && !sid))
		return EINVAL;

	voice  = len / FRAME_BYTES;
	frames = voice + (sid ? 1 : 0);

	/* capacidade conferida antes de escrever; por divisão para não estourar */
	if (frames > *sampc / FRAME_SAMPC)
		return ENOMEM;

	for (i = 0; i < voice; i++)
		bcg729Decoder(st->ctx, &buf[i * FRAME_BYTES], FRAME_BYTES,
			      0, 0, 0, &out[i * FRAME_SAMPC]);

	if (sid)
		bcg729Decoder(st->ctx, &buf[voice * FRAME_BYTES], SID_BYTES,
			      0, 1, 0, &out[voice * FRAME_SAMPC]);

	st->last_frames = frames;
	*sampc = frames * FRAME_SAMPC;

	return 0;
}


/* Chamado uma vez por pacote perdido: repõe o tamanho do último pacote recebido.
 * buf/len (pacote seguinte, só para FEC) não servem ao G.729. */
static int plc(struct audec_state *st, int fmt, void *sampv, size_t *sampc,
	       const uint8_t *buf, size_t len)
{
	int16_t *out = sampv;
	size_t frames, i;
	(void)buf;
	(void)len;

	if (!st || !sampv || !sampc)
		return EINVAL;

	if (fmt != AUFMT_S16LE)
		return ENOTSUP;

	frames = st->last_frames;
	if (frames > *sampc / FRAME_SAMPC)
		frames = *sampc / FRAME_SAMPC;
	if (!frames)
		return ENOMEM;

	for (i = 0; i < frames; i++)
		bcg729Decoder(st->ctx, NULL, 0, 1, 0, 0,
			      &out[i * FRAME_SAMPC]);

	*sampc = frames * FRAME_SAMPC;

	return 0;
}


static struct aucodec g729 = {
	.pt      = "18",
	.name    = "G729",
	.srate   = 8000,
	.crate   = 8000,
	.ch      = 1,
	.pch     = 1,
	.fmtp    = "annexb=no",
	.encupdh = encode_update,
	.ench    = encode,
	.decupdh = decode_update,
	.dech    = decode,
	.plch    = plc,
};


static int module_init(void)
{
	/* Texto único: o CI procura esta string no baresip.exe (o CMake pula módulo calado). */
	info("g729: codec G.729 via libbcg729, annexb=no\n");
	aucodec_register(baresip_aucodecl(), &g729);
	return 0;
}


static int module_close(void)
{
	aucodec_unregister(&g729);
	return 0;
}


EXPORT_SYM const struct mod_export DECL_EXPORTS(g729) = {
	"g729",
	"codec",
	module_init,
	module_close
};
