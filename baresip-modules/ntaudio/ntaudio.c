/* SPDX-License-Identifier: GPL-3.0-or-later
 * Copyright (C) 2026 NTWeb
 */
/**
 * @file ntaudio.c  Ganho de microfone/alto-falante e troca de dispositivo em chamada (NT-Fone)
 *
 * O baresip não tem volume de reprodução, e os comandos do menu recusam dispositivos
 * fora da lista que o wasapi montou no init (e nunca aceitam "default").
 *
 * Config: ntaudio_src_gain / ntaudio_play_gain (0.0 a 4.0, padrão 1.0).
 * Comandos: ntaudio_src_gain <g>, ntaudio_play_gain <g>,
 *           ntaudio_player <mod>,<dev>, ntaudio_source <mod>,<dev>
 *
 * Teste de áudio (só fora de chamada), nos dispositivos escolhidos em conf_config():
 *           ntaudio_tone, ntaudio_mictest off|meter|loop, ntaudio_level
 *
 * Toque de chamada recebida (sintetizado, no alert_* da config, que o ntaudio_player acompanha; o app controla quando):
 *           ntaudio_ring on|off|preview [<id>] (preview toca um período, do toque escolhido ou do <id>, e para sozinho),
 *           ntaudio_ringtone <trinado|suave|digital|sino>
 *
 * Câmera (o nome tem espaços e não cabe no arquivo de config; vale na chamada em andamento e nas próximas):
 *           ntaudio_camera <mod>,<dev>
 */

#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <re.h>
#include <rem.h>
#include <baresip.h>
#ifdef WIN32
#include <windows.h>
#endif


#define GAIN_MAX 4.0

#define TEST_SRATE   48000
#define TEST_PTIME   20
#define TONE_MS      600
#define TONE_SAMPLES (TEST_SRATE / 1000 * TONE_MS)
#define TONE_MARGIN  300     /* ms além do tom, para o driver esvaziar o buffer */
#define LOOP_MIN     3840    /* bytes: 40 ms de pré-carga */
#define LOOP_MAX     19200   /* bytes: 200 ms, teto de latência */
#define MICTEST_MS   120000  /* o teste se desliga sozinho */
#define PEAK_SCALE   32768.0

#define RING_MAX_SAMPLES (TEST_SRATE * 3)  /* o maior período (trinado e sino: 3 s) */
#define RING_ATTACK  0.005   /* s */
#define RING_RELEASE 0.010   /* s */
#define RING_PEAK    0.5     /* fração do fundo de escala */

struct ntaudio_enc {
	struct aufilt_enc_st af;  /* base class */
};

struct ntaudio_dec {
	struct aufilt_dec_st af;  /* base class */
};

/* double simples entre a thread do ctrl_tcp e as de áudio: escrita alinhada de 8 bytes é atômica em x86-64/arm64. */
static double src_gain  = 1.0;
static double play_gain = 1.0;

enum mictest_mode { MODE_OFF, MODE_METER, MODE_LOOP };

static struct {
	enum mictest_mode mode;
	struct ausrc_st *src;
	struct auplay_st *play;
	struct aubuf *ab;
	struct tmr tmr;
	double peak;  /* pico desde a última leitura; a thread de áudio escreve, a principal zera (corrida inofensiva) */
} mt;

static struct {
	struct auplay_st *play;
	struct tmr tmr;
	size_t pos;  /* só a thread do player escreve; a principal zera com o player parado */
} tone;

static int16_t tone_buf[TONE_SAMPLES];

static struct {
	struct auplay_st *play;
	struct tmr tmr;
	size_t pos;   /* só a thread do player escreve; a principal zera com o player parado */
	size_t len;   /* amostras do período do toque em ring_buf */
	size_t shown; /* índice em ringtones[] que está em ring_buf */
	bool once;    /* prévia: toca um período e depois só silêncio */
} ring;

static int16_t ring_buf[RING_MAX_SAMPLES];

/* Toques: id estável (vai no audio.json e no comando) e período em segundos. A forma de onda está em ring_render(). */
static const struct {
	const char *id;
	double secs;
} ringtones[] = {
	{"trinado", 3.0},
	{"suave", 2.5},
	{"digital", 2.0},
	{"sino", 3.0},
};
static size_t ring_sel;  /* toque escolhido: índice em ringtones[] */


static void enc_destructor(void *arg)
{
	struct ntaudio_enc *st = arg;

	list_unlink(&st->af.le);
}


static void dec_destructor(void *arg)
{
	struct ntaudio_dec *st = arg;

	list_unlink(&st->af.le);
}


/* Nunca falha por formato: o filtro só deixa passar o que não conhece. */
static int encode_update(struct aufilt_enc_st **stp, void **ctx,
			 const struct aufilt *af, struct aufilt_prm *prm,
			 const struct audio *au)
{
	struct ntaudio_enc *st;
	(void)ctx;
	(void)af;
	(void)au;

	if (!stp || !prm)
		return EINVAL;

	st = mem_zalloc(sizeof(*st), enc_destructor);
	if (!st)
		return ENOMEM;

	*stp = (struct aufilt_enc_st *)st;

	return 0;
}


static int decode_update(struct aufilt_dec_st **stp, void **ctx,
			 const struct aufilt *af, struct aufilt_prm *prm,
			 const struct audio *au)
{
	struct ntaudio_dec *st;
	(void)ctx;
	(void)af;
	(void)au;

	if (!stp || !prm)
		return EINVAL;

	st = mem_zalloc(sizeof(*st), dec_destructor);
	if (!st)
		return ENOMEM;

	*stp = (struct aufilt_dec_st *)st;

	return 0;
}


static int apply_gain(struct auframe *af, double gain)
{
	size_t i;

	if (!af)
		return EINVAL;

	if (gain == 1.0 || !af->sampv)
		return 0;

	switch (af->fmt) {

	case AUFMT_S16LE: {
		int16_t *v = af->sampv;

		for (i = 0; i < af->sampc; i++) {
			double s = v[i] * gain;

			/* Acima de 1.0 usa limitador suave em vez de corte duro. */
			if (gain > 1.0)
				s = tanh(s / 32768.0) * 32767.0;
			else if (s > 32767.0)
				s = 32767.0;
			else if (s < -32768.0)
				s = -32768.0;

			v[i] = (int16_t)s;
		}
		break;
	}

	case AUFMT_FLOAT: {
		float *v = af->sampv;

		for (i = 0; i < af->sampc; i++) {
			double s = v[i] * gain;

			if (gain > 1.0)
				s = tanh(s);
			else if (s > 1.0)
				s = 1.0;
			else if (s < -1.0)
				s = -1.0;

			v[i] = (float)s;
		}
		break;
	}

	default:
		break;
	}

	return 0;
}


static int encode_frame(struct aufilt_enc_st *st, struct auframe *af)
{
	(void)st;

	return apply_gain(af, src_gain);
}


static int decode_frame(struct aufilt_dec_st *st, struct auframe *af)
{
	(void)st;

	return apply_gain(af, play_gain);
}


static struct aufilt ntaudio = {
	.name    = "ntaudio",
	.encupdh = encode_update,
	.ench    = encode_frame,
	.decupdh = decode_update,
	.dech    = decode_frame
};


static int set_gain(struct re_printf *pf, const char *prm, const char *name,
		    double *gain)
{
	char *end = NULL;
	double g;

	if (!str_isset(prm))
		return EINVAL;

	g = strtod(prm, &end);
	if (end == prm || *end != '\0' || !(g >= 0.0 && g <= GAIN_MAX)) {
		warning("ntaudio: ganho inválido '%s'\n", prm);
		return EINVAL;
	}

	*gain = g;

	return re_hprintf(pf, "ntaudio: %s %.2f\n", name, g);
}


static int cmd_src_gain(struct re_printf *pf, void *arg)
{
	const struct cmd_arg *carg = arg;

	return set_gain(pf, carg->prm, "src_gain", &src_gain);
}


static int cmd_play_gain(struct re_printf *pf, void *arg)
{
	const struct cmd_arg *carg = arg;

	return set_gain(pf, carg->prm, "play_gain", &play_gain);
}


static bool has_call(void)
{
	struct le *le;

	for (le = list_head(uag_list()); le; le = le->next) {
		if (list_head(ua_calls(le->data)))
			return true;
	}

	return false;
}


static void mictest_stop(void)
{
	tmr_cancel(&mt.tmr);
	mt.src = mem_deref(mt.src);  /* a fonte primeiro: ela escreve no aubuf */
	mt.play = mem_deref(mt.play);
	mt.ab = mem_deref(mt.ab);
	mt.mode = MODE_OFF;
	mt.peak = 0.0;
}


static void mictest_timeout(void *arg)
{
	(void)arg;
	mictest_stop();
}


static void mictest_read(struct auframe *af, void *arg)
{
	const int16_t *v = af->sampv;
	double peak = 0.0;
	size_t i;
	(void)arg;

	if (af->fmt != AUFMT_S16LE)
		return;

	apply_gain(af, src_gain);

	for (i = 0; i < af->sampc; i++) {
		double s = (v[i] < 0 ? -(double)v[i] : (double)v[i]) / PEAK_SCALE;

		if (s > peak)
			peak = s;
	}

	if (peak > mt.peak)
		mt.peak = peak;

	if (mt.ab)
		aubuf_write_auframe(mt.ab, af);
}


static void mictest_write(struct auframe *af, void *arg)
{
	(void)arg;

	aubuf_read_auframe(mt.ab, af);  /* silêncio quando falta amostra */
	apply_gain(af, play_gain);
}


static void mictest_error(int err, const char *str, void *arg)
{
	(void)arg;
	warning("ntaudio: erro na fonte do teste (%m) %s\n", err, str);
}


static int mictest_start(enum mictest_mode mode)
{
	const struct config_audio *a = &conf_config()->audio;
	struct ausrc_prm sprm = {TEST_SRATE, 1, TEST_PTIME, AUFMT_S16LE, 0};
	struct auplay_prm pprm = {TEST_SRATE, 1, TEST_PTIME, AUFMT_S16LE};
	int err = 0;

	mictest_stop();

	if (mode == MODE_OFF)
		return 0;

	if (has_call())
		return EBUSY;

	if (mode == MODE_LOOP) {
		err = aubuf_alloc(&mt.ab, LOOP_MIN, LOOP_MAX);
		if (!err)
			err = auplay_alloc(&mt.play, baresip_auplayl(),
					   a->play_mod, &pprm, a->play_dev,
					   mictest_write, NULL);
	}

	if (!err)
		err = ausrc_alloc(&mt.src, baresip_ausrcl(), a->src_mod,
				  &sprm, a->src_dev, mictest_read,
				  mictest_error, NULL);
	if (err) {
		warning("ntaudio: teste do microfone falhou (%m)\n", err);
		mictest_stop();
		return err;
	}

	mt.mode = mode;
	tmr_start(&mt.tmr, MICTEST_MS, mictest_timeout, NULL);

	return 0;
}


static void tone_stop(void)
{
	tmr_cancel(&tone.tmr);
	tone.play = mem_deref(tone.play);
}


static void tone_timeout(void *arg)
{
	(void)arg;
	tone_stop();  /* nunca dentro do write handler do próprio player */
}


static void tone_write(struct auframe *af, void *arg)
{
	int16_t *v = af->sampv;
	size_t left = tone.pos < TONE_SAMPLES ? TONE_SAMPLES - tone.pos : 0;
	size_t n = af->sampc < left ? af->sampc : left;
	(void)arg;

	if (af->fmt != AUFMT_S16LE)
		return;

	memcpy(v, tone_buf + tone.pos, n * sizeof(*v));
	memset(v + n, 0, (af->sampc - n) * sizeof(*v));
	tone.pos += n;

	apply_gain(af, play_gain);
}


/* Dois parciais com ataque de 5 ms e decaimento exponencial, calculados uma vez. */
static void tone_init(void)
{
	const double pi = 3.14159265358979323846;
	const double attack = TEST_SRATE * 0.005;
	size_t i;

	for (i = 0; i < TONE_SAMPLES; i++) {
		double t = (double)i / TEST_SRATE;
		double env = exp(-t * 7.0) * ((double)i < attack ? i / attack : 1.0);
		double s = sin(2.0 * pi * 880.0 * t) +
			   0.5 * sin(2.0 * pi * 1320.0 * t);

		tone_buf[i] = (int16_t)(s / 1.5 * env * 0.6 * 32767.0);
	}
}


/* Soma uma nota em ring_buf: parciais (freq, amplitude relativa), decaimento exp(-decay*t) (0 = plano),
 * tremolo em Hz (0 = sem), ataque e release curtos. Pico da nota = RING_PEAK. */
static void ring_note(double start, double secs, const double *freq,
		      const double *amp, size_t np, double decay, double trem)
{
	const double pi = 3.14159265358979323846;
	const size_t i0 = (size_t)(start * TEST_SRATE);
	size_t n = (size_t)(secs * TEST_SRATE);
	double norm = 0.0;
	size_t p, i;

	if (i0 >= ring.len)
		return;
	if (n > ring.len - i0)
		n = ring.len - i0;

	for (p = 0; p < np; p++)
		norm += amp[p];

	for (i = 0; i < n; i++) {
		double t = (double)i / TEST_SRATE;
		double left = (double)(n - i) / TEST_SRATE;
		double env = decay > 0.0 ? exp(-decay * t) : 1.0;
		double s = 0.0;
		int v;

		if (t < RING_ATTACK)
			env *= t / RING_ATTACK;
		if (left < RING_RELEASE)
			env *= left / RING_RELEASE;
		if (trem > 0.0)
			env *= 0.5 + 0.5 * sin(2.0 * pi * trem * t);

		for (p = 0; p < np; p++)
			s += amp[p] * sin(2.0 * pi * freq[p] * t);

		v = ring_buf[i0 + i] + (int)(s / norm * env * RING_PEAK * 32767.0);
		ring_buf[i0 + i] = (int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v);
	}
}


/* Sintetiza o toque idx em ring_buf (player parado). */
static void ring_render(size_t idx)
{
	static const double two_a[] = {1.0, 0.5};
	static const double bell_a[] = {1.0, 0.6, 0.3};
	static const double one_a[] = {1.0};
	static const double trinado_f[] = {880.0, 1320.0};
	static const double bell_f[] = {660.0, 660.0 * 2.76, 660.0 * 5.4};
	static const double marimba_a[] = {1.0, 0.25};
	static const double c6[] = {1046.5, 4186.0};
	static const double e6[] = {1318.5, 5274.0};
	static const double g6[] = {1568.0, 6272.0};
	static const double digital_f[] = {1000.0, 1200.0};
	size_t k;

	ring.shown = idx;
	ring.len = (size_t)(ringtones[idx].secs * TEST_SRATE);
	memset(ring_buf, 0, sizeof(ring_buf));

	switch (idx) {

	case 0:  /* trinado: 880 Hz + quinta, tremolo de 20 Hz, 2 toques de 0,4 s */
		ring_note(0.0, 0.4, trinado_f, two_a, 2, 0.0, 20.0);
		ring_note(0.6, 0.4, trinado_f, two_a, 2, 0.0, 20.0);
		break;

	case 1:  /* suave: dó-mi-sol tipo marimba */
		ring_note(0.00, 0.5, c6, marimba_a, 2, 10.0, 0.0);
		ring_note(0.15, 0.5, e6, marimba_a, 2, 10.0, 0.0);
		ring_note(0.30, 0.5, g6, marimba_a, 2, 10.0, 0.0);
		break;

	case 2:  /* digital: 4 bipes de 80 ms, 1000/1200 Hz alternados */
		for (k = 0; k < 4; k++)
			ring_note(k * 0.12, 0.08, &digital_f[k % 2], one_a, 1, 0.0, 0.0);
		break;

	case 3:  /* sino: 2 batidas com parciais inarmônicos */
		ring_note(0.0, 1.4, bell_f, bell_a, 3, 4.0, 0.0);
		ring_note(1.5, 1.4, bell_f, bell_a, 3, 4.0, 0.0);
		break;
	}
}


static void ring_write(struct auframe *af, void *arg)
{
	int16_t *v = af->sampv;
	size_t done = 0;
	(void)arg;

	if (af->fmt != AUFMT_S16LE)
		return;

	while (done < af->sampc) {
		size_t n = ring.len - ring.pos;

		if (ring.once && !n) {
			memset(v + done, 0, (af->sampc - done) * sizeof(*v));
			break;
		}

		if (n > af->sampc - done)
			n = af->sampc - done;

		memcpy(v + done, ring_buf + ring.pos, n * sizeof(*v));
		done += n;
		ring.pos += n;
		if (ring.pos == ring.len && !ring.once)
			ring.pos = 0;
	}
}


static void ring_stop(void)
{
	tmr_cancel(&ring.tmr);
	ring.play = mem_deref(ring.play);
}


static void ring_timeout(void *arg)
{
	(void)arg;
	ring_stop();  /* nunca dentro do write handler do próprio player */
}


/* once: prévia de um período, que se encerra sozinha. Toca o toque idx no alert_* (o ntaudio_player o acompanha), senão no play_*. */
static int ring_start(bool once, size_t idx)
{
	const struct config_audio *a = &conf_config()->audio;
	struct auplay_prm prm = {TEST_SRATE, 1, TEST_PTIME, AUFMT_S16LE};
	const char *mod = a->alert_mod, *dev = a->alert_dev;
	int err;

	ring_stop();

	if (!mod[0]) {
		mod = a->play_mod;
		dev = a->play_dev;
	}

	if (ring.shown != idx)
		ring_render(idx);  /* player parado: ring_stop() acima */

	ring.pos = 0;
	ring.once = once;
	err = auplay_alloc(&ring.play, baresip_auplayl(), mod, &prm, dev,
			   ring_write, NULL);
	if (err) {
		warning("ntaudio: toque falhou (%m)\n", err);
		return err;
	}

	if (once)
		tmr_start(&ring.tmr, ringtones[idx].secs * 1000 + TONE_MARGIN,
			  ring_timeout, NULL);

	return 0;
}


static int tone_start(void)
{
	const struct config_audio *a = &conf_config()->audio;
	struct auplay_prm prm = {TEST_SRATE, 1, TEST_PTIME, AUFMT_S16LE};
	int err;

	tone_stop();

	if (has_call())
		return EBUSY;

	tone.pos = 0;
	err = auplay_alloc(&tone.play, baresip_auplayl(), a->play_mod, &prm,
			   a->play_dev, tone_write, NULL);
	if (err) {
		warning("ntaudio: tom de teste falhou (%m)\n", err);
		return err;
	}

	tmr_start(&tone.tmr, TONE_MS + TONE_MARGIN, tone_timeout, NULL);

	return 0;
}


static void event_handler(enum bevent_ev ev, struct bevent *event, void *arg)
{
	(void)ev;
	(void)arg;

	/* qualquer evento de chamada libera os dispositivos */
	if (bevent_get_call(event)) {
		mictest_stop();
		tone_stop();
	}
}


static int cmd_tone(struct re_printf *pf, void *arg)
{
	int err = tone_start();

	(void)arg;

	return err ? err : re_hprintf(pf, "ntaudio: tone\n");
}


/* Índice do toque com esse id, ou RE_ARRAY_SIZE(ringtones) se não existe. */
static size_t ring_find(const char *id)
{
	size_t i;

	for (i = 0; i < RE_ARRAY_SIZE(ringtones); i++)
		if (!str_cmp(id, ringtones[i].id))
			break;

	return i;
}


static int cmd_ring(struct re_printf *pf, void *arg)
{
	const struct cmd_arg *carg = arg;
	size_t idx = ring_sel;
	int err = 0;

	if (!str_cmp(carg->prm, "on"))
		err = ring_start(false, ring_sel);
	else if (!str_cmp(carg->prm, "off"))
		ring_stop();
	else if (!str_ncmp(carg->prm, "preview", 7) &&
		 (!carg->prm[7] || carg->prm[7] == ' ')) {
		/* a prévia de outro toque não muda o escolhido */
		if (carg->prm[7] && (idx = ring_find(carg->prm + 8)) == RE_ARRAY_SIZE(ringtones))
			return EINVAL;
		err = has_call() ? EBUSY : ring_start(true, idx);
	}
	else
		return EINVAL;

	return err ? err : re_hprintf(pf, "ntaudio: ring %s\n", carg->prm);
}


/* Troca o toque; se estiver tocando (ou em prévia), recomeça com o novo. */
static int cmd_ringtone(struct re_printf *pf, void *arg)
{
	const struct cmd_arg *carg = arg;
	bool playing = ring.play != NULL, once = ring.once;
	size_t i = ring_find(carg->prm);
	int err = 0;

	if (i == RE_ARRAY_SIZE(ringtones))
		return EINVAL;

	ring_sel = i;
	if (playing)
		err = ring_start(once, i);

	return err ? err : re_hprintf(pf, "ntaudio: ringtone %s\n", carg->prm);
}


static int cmd_mictest(struct re_printf *pf, void *arg)
{
	const struct cmd_arg *carg = arg;
	enum mictest_mode mode;
	int err;

	if (!str_cmp(carg->prm, "off"))
		mode = MODE_OFF;
	else if (!str_cmp(carg->prm, "meter"))
		mode = MODE_METER;
	else if (!str_cmp(carg->prm, "loop"))
		mode = MODE_LOOP;
	else
		return EINVAL;

	err = mictest_start(mode);

	return err ? err : re_hprintf(pf, "ntaudio: mictest %s\n", carg->prm);
}


static int cmd_level(struct re_printf *pf, void *arg)
{
	static const char *const names[] = {"off", "meter", "loop"};
	double peak = mt.peak;
	(void)arg;

	mt.peak = 0.0;

	return re_hprintf(pf, "%s %.4f\n", names[mt.mode], peak);
}


/* Como switch_audio_player/source do menu, sem a checagem da dev_list. */
static int switch_dev(struct re_printf *pf, const char *prm, bool player)
{
	struct pl pl_driver, pl_device;
	struct config_audio *aucfg;
	struct config *cfg;
	char driver[16], device[128] = "";
	struct le *le, *leu;
	int err;

	if (re_regex(prm, str_len(prm), "[^,]+,[~]*", &pl_driver, &pl_device))
		return EINVAL;

	if (pl_driver.l >= sizeof(driver) || pl_device.l >= sizeof(device))
		return EINVAL;

	pl_strcpy(&pl_driver, driver, sizeof(driver));
	pl_strcpy(&pl_device, device, sizeof(device));

	cfg = conf_config();
	if (!cfg)
		return EINVAL;

	aucfg = &cfg->audio;

	if (player) {
		str_ncpy(aucfg->play_mod, driver, sizeof(aucfg->play_mod));
		str_ncpy(aucfg->play_dev, device, sizeof(aucfg->play_dev));
		str_ncpy(aucfg->alert_mod, driver, sizeof(aucfg->alert_mod));
		str_ncpy(aucfg->alert_dev, device, sizeof(aucfg->alert_dev));
	}
	else {
		str_ncpy(aucfg->src_mod, driver, sizeof(aucfg->src_mod));
		str_ncpy(aucfg->src_dev, device, sizeof(aucfg->src_dev));
	}

	/* teste em andamento reabre nos dispositivos novos; o tom só para */
	tone_stop();
	if (mt.mode != MODE_OFF)
		mictest_start(mt.mode);

	for (leu = list_head(uag_list()); leu; leu = leu->next) {
		struct ua *ua = leu->data;

		for (le = list_tail(ua_calls(ua)); le; le = le->prev) {
			struct audio *a = call_audio(le->data);

			err = player ? audio_set_player(a, driver, device)
				     : audio_set_source(a, driver, device);
			if (err) {
				warning("ntaudio: falha ao trocar o "
					"dispositivo (%m)\n", err);
				return err;
			}
		}
	}

	return re_hprintf(pf, "ntaudio: %s %s,%s\n",
			  player ? "player" : "source", driver, device);
}


static int cmd_player(struct re_printf *pf, void *arg)
{
	const struct cmd_arg *carg = arg;

	return switch_dev(pf, carg->prm, true);
}


static int cmd_source(struct re_printf *pf, void *arg)
{
	const struct cmd_arg *carg = arg;

	return switch_dev(pf, carg->prm, false);
}


#ifdef WIN32
/* O dshow compara o nome da câmera em ANSI (CP_ACP); o app manda UTF-8. */
static int utf8_to_ansi(char *dev, size_t sz)
{
	wchar_t w[128];
	char a[128];
	BOOL lossy = FALSE;

	if (!dev[0])
		return 0;

	if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, dev, -1,
				 w, RE_ARRAY_SIZE(w)))
		return EINVAL;

	if (!WideCharToMultiByte(CP_ACP, 0, w, -1, a, sizeof(a), NULL,
				 &lossy) || lossy)
		return EINVAL;

	str_ncpy(dev, a, sz);
	return 0;
}
#endif


/* O /vidsrc do menu devolve sucesso em falha e recusa dispositivo vazio (= primeira câmera). */
static int cmd_camera(struct re_printf *pf, void *arg)
{
	const struct cmd_arg *carg = arg;
	struct pl pl_driver, pl_device;
	struct config *cfg;
	char driver[16], device[128] = "";
	struct le *le, *leu;
	int err;

	if (re_regex(carg->prm, str_len(carg->prm), "[^,]+,[~]*",
		     &pl_driver, &pl_device))
		return EINVAL;

	if (pl_driver.l >= sizeof(driver) || pl_device.l >= sizeof(device))
		return EINVAL;

	pl_strcpy(&pl_driver, driver, sizeof(driver));
	pl_strcpy(&pl_device, device, sizeof(device));

#ifdef WIN32
	err = utf8_to_ansi(device, sizeof(device));
	if (err)
		return err;
#endif

	cfg = conf_config();
	if (!cfg)
		return EINVAL;

	str_ncpy(cfg->video.src_mod, driver, sizeof(cfg->video.src_mod));
	str_ncpy(cfg->video.src_dev, device, sizeof(cfg->video.src_dev));

	for (leu = list_head(uag_list()); leu; leu = leu->next) {
		struct ua *ua = leu->data;

		for (le = list_tail(ua_calls(ua)); le; le = le->prev) {
			struct video *v = call_video(le->data);

			if (!v)
				continue;

			/* o botão Vídeo, ao ligar depois, abre este nome */
			video_set_devicename(v, device, video_get_disp_dev(v));

			/* só troca a fonte se a câmera já está aberta */
			if (!(sdp_media_dir(stream_sdpmedia(video_strm(v))) &
			      SDP_SENDONLY))
				continue;

			err = video_set_source(v, driver, device);
			if (err) {
				warning("ntaudio: falha ao trocar a "
					"câmera (%m)\n", err);
				return err;
			}
		}
	}

	return re_hprintf(pf, "ntaudio: camera %s,%s\n", driver, device);
}


static const struct cmd cmdv[] = {
	{"ntaudio_src_gain",  0, CMD_PRM, "Ganho do microfone <0.0-4.0>", cmd_src_gain},
	{"ntaudio_play_gain", 0, CMD_PRM, "Ganho do alto-falante <0.0-4.0>", cmd_play_gain},
	{"ntaudio_player",    0, CMD_PRM, "Trocar player <mod>,<dev>", cmd_player},
	{"ntaudio_source",    0, CMD_PRM, "Trocar source <mod>,<dev>", cmd_source},
	{"ntaudio_tone",      0, 0,       "Tocar o tom de teste", cmd_tone},
	{"ntaudio_mictest",   0, CMD_PRM, "Teste do microfone <off|meter|loop>", cmd_mictest},
	{"ntaudio_level",     0, 0,       "Pico do microfone <modo> <0-1>", cmd_level},
	{"ntaudio_ring",      0, CMD_PRM, "Toque de chamada <on|off|preview>", cmd_ring},
	{"ntaudio_ringtone",  0, CMD_PRM, "Som do toque <id>", cmd_ringtone},
	{"ntaudio_camera",    0, CMD_PRM, "Câmera <mod>,<dev>", cmd_camera},
};


static void read_gain(const char *name, double *gain)
{
	double g = *gain;

	if (conf_get_float(conf_cur(), name, &g) == 0)
		*gain = g < 0.0 ? 0.0 : (g > GAIN_MAX ? GAIN_MAX : g);
}


static int module_init(void)
{
	int err;

	read_gain("ntaudio_src_gain", &src_gain);
	read_gain("ntaudio_play_gain", &play_gain);

	tone_init();
	ring_render(ring_sel);
	aufilt_register(baresip_aufiltl(), &ntaudio);

	err = bevent_register(event_handler, NULL);
	if (err)
		return err;

	return cmd_register(baresip_commands(), cmdv, RE_ARRAY_SIZE(cmdv));
}


static int module_close(void)
{
	bevent_unregister(event_handler);
	mictest_stop();
	tone_stop();
	ring_stop();
	aufilt_unregister(&ntaudio);
	cmd_unregister(baresip_commands(), cmdv);

	return 0;
}


EXPORT_SYM const struct mod_export DECL_EXPORTS(ntaudio) = {
	"ntaudio",
	"filter",
	module_init,
	module_close
};
