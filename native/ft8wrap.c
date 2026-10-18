/* Couche d'appel de ft8_lib pour CAT Pilot (Python, ctypes).
 *
 *   ft8w_decode : décode un créneau (12 000 Hz, FT8 15 s ou FT4 7,5 s)
 *   ft8w_encode : texte du message -> tonalités (79 pour FT8, 105 pour FT4)
 *   ft8w_hash_add : mémorise un indicatif (pour lire les <...> des indicatifs composés)
 */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <stdbool.h>

#include <ft8/decode.h>
#include <ft8/encode.h>
#include <ft8/message.h>
#include <ft8/constants.h>
#include <common/monitor.h>

#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

typedef struct
{
    char text[40];
    float freq;
    float dt;
    float score;
    int ldpc_errors;
} ft8w_result_t;

/* --- table des indicatifs vus (hachage) -------------------------------------------------- */
#define HT_SIZE 1024
static struct
{
    char callsign[12];
    uint32_t hash;
} ht[HT_SIZE];

static void ht_cleanup(uint8_t max_age)
{
    for (int i = 0; i < HT_SIZE; ++i)
    {
        if (ht[i].callsign[0] != '\0')
        {
            uint8_t age = (uint8_t)(ht[i].hash >> 24);
            if (age > max_age)
            {
                ht[i].callsign[0] = '\0';
                ht[i].hash = 0;
            }
            else
                ht[i].hash = (((uint32_t)age + 1u) << 24) | (ht[i].hash & 0x3FFFFFu);
        }
    }
}

static void ht_add(const char* callsign, uint32_t hash)
{
    uint16_t hash10 = (hash >> 12) & 0x3FFu;
    int idx = (hash10 * 23) % HT_SIZE;
    for (int n = 0; n < HT_SIZE && ht[idx].callsign[0] != '\0'; ++n)
    {
        if (((ht[idx].hash & 0x3FFFFFu) == hash) && 0 == strcmp(ht[idx].callsign, callsign))
        {
            ht[idx].hash &= 0x3FFFFFu;
            return;
        }
        idx = (idx + 1) % HT_SIZE;
    }
    strncpy(ht[idx].callsign, callsign, 11);
    ht[idx].callsign[11] = '\0';
    ht[idx].hash = hash;
}

static bool ht_lookup(ftx_callsign_hash_type_t hash_type, uint32_t hash, char* callsign)
{
    uint8_t shift = (hash_type == FTX_CALLSIGN_HASH_10_BITS) ? 12 : (hash_type == FTX_CALLSIGN_HASH_12_BITS ? 10 : 0);
    uint16_t hash10 = (hash >> (12 - shift)) & 0x3FFu;
    int idx = (hash10 * 23) % HT_SIZE;
    for (int n = 0; n < HT_SIZE && ht[idx].callsign[0] != '\0'; ++n)
    {
        if (((ht[idx].hash & 0x3FFFFFu) >> shift) == hash)
        {
            strcpy(callsign, ht[idx].callsign);
            return true;
        }
        idx = (idx + 1) % HT_SIZE;
    }
    callsign[0] = '\0';
    return false;
}

static ftx_callsign_hash_interface_t hash_if = { .lookup_hash = ht_lookup, .save_hash = ht_add };

EXPORT void ft8w_hash_add(const char* call)
{
    /* on passe par un encodage « CQ <call> » : ft8_lib calcule et mémorise le hachage */
    ftx_message_t msg;
    char text[40];
    snprintf(text, sizeof(text), "CQ %s", call);
    ftx_message_encode(&msg, &hash_if, text);
}

static int cfg_min_score = 5, cfg_max_cand = 300, cfg_ldpc = 40, cfg_tosr = 4, cfg_fosr = 2;

EXPORT void ft8w_config(int min_score, int max_cand, int ldpc_iter, int time_osr, int freq_osr)
{
    cfg_min_score = min_score;
    cfg_max_cand = max_cand > 400 ? 400 : max_cand;
    cfg_ldpc = ldpc_iter;
    cfg_tosr = time_osr;
    cfg_fosr = freq_osr;
}

EXPORT int ft8w_decode(const float* signal, int num_samples, int sample_rate, int is_ft4,
                       float f_min, float f_max, ft8w_result_t* out, int max_out)
{
    const int kMin_score = cfg_min_score, kMax_candidates = cfg_max_cand, kLDPC_iterations = cfg_ldpc;
    monitor_t mon;
    monitor_config_t cfg = { .f_min = f_min, .f_max = f_max, .sample_rate = sample_rate,
                             .time_osr = cfg_tosr, .freq_osr = cfg_fosr,
                             .protocol = is_ft4 ? FTX_PROTOCOL_FT4 : FTX_PROTOCOL_FT8 };
    monitor_init(&mon, &cfg);
    for (int pos = 0; pos + mon.block_size <= num_samples; pos += mon.block_size)
        monitor_process(&mon, signal + pos);

    ftx_candidate_t* cands = (ftx_candidate_t*)malloc(sizeof(ftx_candidate_t) * kMax_candidates);
    int n_cand = ftx_find_candidates(&mon.wf, kMax_candidates, cands, kMin_score);
    int n_out = 0;
    static uint8_t seen[256][FTX_PAYLOAD_LENGTH_BYTES];
    int n_seen = 0;
    for (int i = 0; i < n_cand && n_out < max_out; ++i)
    {
        const ftx_candidate_t* c = &cands[i];
        ftx_message_t msg;
        ftx_decode_status_t st;
        if (!ftx_decode_candidate(&mon.wf, c, kLDPC_iterations, &msg, &st))
            continue;
        bool dup = false;
        for (int k = 0; k < n_seen; ++k)
            if (0 == memcmp(seen[k], msg.payload, FTX_PAYLOAD_LENGTH_BYTES))
            {
                dup = true;
                break;
            }
        if (dup)
            continue;
        if (n_seen < 256)
            memcpy(seen[n_seen++], msg.payload, FTX_PAYLOAD_LENGTH_BYTES);
        ftx_message_offsets_t offsets;
        char text[FTX_MAX_MESSAGE_LENGTH];
        if (ftx_message_decode(&msg, &hash_if, text, &offsets) != FTX_MESSAGE_RC_OK)
            continue;
        ft8w_result_t* r = &out[n_out++];
        strncpy(r->text, text, sizeof(r->text) - 1);
        r->text[sizeof(r->text) - 1] = '\0';
        r->freq = (mon.min_bin + c->freq_offset + (float)c->freq_sub / mon.wf.freq_osr) / mon.symbol_period;
        r->dt = (c->time_offset + (float)c->time_sub / mon.wf.time_osr) * mon.symbol_period;
        r->score = c->score;
        r->ldpc_errors = st.ldpc_errors;
    }
    free(cands);
    monitor_free(&mon);
    ht_cleanup(40);
    return n_out;
}

EXPORT int ft8w_encode(const char* message, int is_ft4, uint8_t* tones)
{
    ftx_message_t msg;
    ftx_message_rc_t rc = ftx_message_encode(&msg, &hash_if, message);
    if (rc != FTX_MESSAGE_RC_OK)
        return -(int)rc - 1;
    if (is_ft4)
    {
        ft4_encode(msg.payload, tones);
        return FT4_NN;
    }
    ft8_encode(msg.payload, tones);
    return FT8_NN;
}
