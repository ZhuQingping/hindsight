/*
 * Experimental compatibility adapter, not a new relevance policy.
 * Reproduce CPython 3.11's set ordering for canonical UUID strings with
 * PYTHONHASHSEED=0. The RRF primitive itself remains independent of Python.
 *
 * Algorithm references: CPython v3.11.15 Objects/setobject.c and Python/pyhash.c
 * (Python Software Foundation License). SipHash was originally published by
 * Jean-Philippe Aumasson and Daniel J. Bernstein.
 *
 * No Python runtime is loaded. No deletions/tombstones are needed for these
 * constructor/union operations. Callers must reject other runtime contracts.
 */
#include "postgres.h"
#include "fmgr.h"
#include "catalog/pg_type_d.h"
#include "utils/array.h"
#include "utils/hsearch.h"
#include "utils/fmgrprotos.h"
#include "utils/uuid.h"
#include "miscadmin.h"

PG_MODULE_MAGIC;
PG_FUNCTION_INFO_V1(contextbase_cpython311_set_seed0);
PG_FUNCTION_INFO_V1(contextbase_cpython311_union_seed0);

typedef struct LegacyKey
{
	pg_uuid_t id;
	uint64 hash;
} LegacyKey;

typedef struct LegacySet
{
	Size mask;
	Size used;
	LegacyKey **table;
} LegacySet;

typedef struct LegacyKeys
{
	int count;
	LegacyKey **ordered;
} LegacyKeys;

static uint64
rotl64(uint64 v, unsigned int bits)
{
	return (v << bits) | (v >> (64 - bits));
}

static void
sip_round(uint64 *a, uint64 *b, uint64 *c, uint64 *d)
{
	*a += *b;
	*c += *d;
	*b = rotl64(*b, 13) ^ *a;
	*d = rotl64(*d, 16) ^ *c;
	*a = rotl64(*a, 32);
	*c += *b;
	*a += *d;
	*b = rotl64(*b, 17) ^ *c;
	*d = rotl64(*d, 21) ^ *a;
	*c = rotl64(*c, 32);
}

static uint64
uuid_string_hash(const pg_uuid_t *id)
{
	const unsigned char *text = (unsigned char *) DatumGetCString(DirectFunctionCall1(uuid_out, UUIDPGetDatum(id)));
	Size len = strlen((const char *) text);
	Size offset = 0;
	uint64 a = UINT64CONST(0x736f6d6570736575);
	uint64 b = UINT64CONST(0x646f72616e646f6d);
	uint64 c = UINT64CONST(0x6c7967656e657261);
	uint64 d = UINT64CONST(0x7465646279746573);
	uint64 tail = ((uint64) len) << 56;
	uint64 result;
	unsigned int j;

	/* CPython seed zero disables hash randomization: both SipHash keys are 0. */
	while (len - offset >= 8)
	{
		uint64 word = 0;
		for (j = 0; j < 8; j++)
			word |= ((uint64) text[offset + j]) << (j * 8);
		d ^= word;
		sip_round(&a, &b, &c, &d);
		a ^= word;
		offset += 8;
	}
	for (j = 0; offset + j < len; j++)
		tail |= ((uint64) text[offset + j]) << (j * 8);
	d ^= tail;
	sip_round(&a, &b, &c, &d);
	a ^= tail;
	c ^= 0xff;
	for (j = 0; j < 3; j++)
		sip_round(&a, &b, &c, &d);
	result = (a ^ b) ^ (c ^ d);
	pfree((void *) text);
	return result == UINT64_MAX ? UINT64_MAX - 1 : result;
}

static LegacySet *
new_set(void)
{
	LegacySet *set = palloc0(sizeof(LegacySet));
	set->mask = 7;
	set->table = palloc0(sizeof(LegacyKey *) * 8);
	return set;
}

static void
clean_insert(LegacyKey **table, Size mask, LegacyKey *key)
{
	Size i = key->hash & mask;
	uint64 perturb = key->hash;

	for (;;)
	{
		Size j;
		if (table[i] == NULL)
		{
			table[i] = key;
			return;
		}
		if (i + 9 <= mask)
			for (j = 1; j <= 9; j++)
				if (table[i + j] == NULL)
				{
					table[i + j] = key;
					return;
				}
		perturb >>= 5;
		i = (i * 5 + 1 + perturb) & mask;
	}
}

static void
resize_set(LegacySet *set, Size minimum)
{
	Size size = 8;
	Size oldmask = set->mask;
	LegacyKey **old = set->table;
	Size i;

	while (size <= minimum)
		size <<= 1;
	if (size == 8 && oldmask == 7)
		return;
	set->table = palloc0(size * sizeof(LegacyKey *));
	set->mask = size - 1;
	for (i = 0; i <= oldmask; i++)
		if (old[i] != NULL)
			clean_insert(set->table, set->mask, old[i]);
	pfree(old);
}

static void
add_key(LegacySet *set, LegacyKey *key)
{
	Size i = key->hash & set->mask;
	uint64 perturb = key->hash;

	for (;;)
	{
		Size probes = i + 9 <= set->mask ? 9 : 0;
		Size j;
		for (j = 0; j <= probes; j++)
		{
			LegacyKey *present = set->table[i + j];
			if (present == NULL)
			{
				set->table[i + j] = key;
				set->used++;
				if (set->used * 5 >= set->mask * 3)
					resize_set(set, set->used > 50000 ? set->used * 2 : set->used * 4);
				return;
			}
			if (present->hash == key->hash && memcmp(&present->id, &key->id, UUID_LEN) == 0)
				return;
		}
		perturb >>= 5;
		i = (i * 5 + 1 + perturb) & set->mask;
	}
}

static LegacyKeys
decode_keys(ArrayType *array)
{
	Datum *items;
	bool *nulls;
	int count;
	LegacyKeys keys;
	HASHCTL ctl;
	HTAB *seen;
	int i;

	if (ARR_NDIM(array) > 1)
		ereport(ERROR, (errcode(ERRCODE_INVALID_PARAMETER_VALUE), errmsg("one-dimensional UUID arrays required")));
	deconstruct_array(array, UUIDOID, UUID_LEN, false, TYPALIGN_CHAR, &items, &nulls, &count);
	if (count > 10000)
		ereport(ERROR, (errcode(ERRCODE_PROGRAM_LIMIT_EXCEEDED), errmsg("legacy adapter supports at most 10000 keys per input")));
	memset(&ctl, 0, sizeof(ctl));
	ctl.keysize = UUID_LEN;
	ctl.entrysize = sizeof(LegacyKey);
	ctl.hcxt = CurrentMemoryContext;
	seen = hash_create("legacy UUID dictionary", Max(count, 16), &ctl, HASH_ELEM | HASH_BLOBS | HASH_CONTEXT);
	keys.count = 0;
	keys.ordered = palloc(sizeof(LegacyKey *) * Max(count, 1));
	for (i = 0; i < count; i++)
	{
		bool found;
		LegacyKey *key;
		if (nulls[i])
			ereport(ERROR, (errcode(ERRCODE_NULL_VALUE_NOT_ALLOWED), errmsg("null UUID keys are not supported")));
		key = hash_search(seen, DatumGetUUIDP(items[i]), HASH_ENTER, &found);
		if (!found)
		{
			key->hash = uuid_string_hash(&key->id);
			keys.ordered[keys.count++] = key;
		}
	}
	return keys;
}

static LegacySet *
from_dictionary(LegacyKeys keys)
{
	LegacySet *set = new_set();
	int i;

	/* set(dict) reserves once using the distinct dictionary key count. */
	if (((Size) keys.count) * 5 >= set->mask * 3)
		resize_set(set, ((Size) keys.count) * 2);
	for (i = 0; i < keys.count; i++)
		add_key(set, keys.ordered[i]);
	return set;
}

static void
merge_set(LegacySet *target, const LegacySet *other)
{
	Size i;
	if (other->used == 0)
		return;
	if ((target->used + other->used) * 5 >= target->mask * 3)
		resize_set(target, (target->used + other->used) * 2);
	if (target->used == 0 && target->mask == other->mask)
	{
		memcpy(target->table, other->table, sizeof(LegacyKey *) * (other->mask + 1));
		target->used = other->used;
		return;
	}
	if (target->used == 0)
	{
		for (i = 0; i <= other->mask; i++)
			if (other->table[i] != NULL)
				clean_insert(target->table, target->mask, other->table[i]);
		target->used = other->used;
		return;
	}
	for (i = 0; i <= other->mask; i++)
		if (other->table[i] != NULL)
			add_key(target, other->table[i]);
}

static LegacySet *
set_union(const LegacySet *left, const LegacySet *right)
{
	LegacySet *result = new_set();
	merge_set(result, left);
	merge_set(result, right);
	return result;
}

static ArrayType *
set_array(const LegacySet *set)
{
	Datum *values;
	Size i;
	int count = 0;
	if (set->used == 0)
		return construct_empty_array(UUIDOID);
	values = palloc(sizeof(Datum) * set->used);
	for (i = 0; i <= set->mask; i++)
		if (set->table[i] != NULL)
			values[count++] = UUIDPGetDatum(&set->table[i]->id);
	return construct_array(values, count, UUIDOID, UUID_LEN, false, TYPALIGN_CHAR);
}

Datum
contextbase_cpython311_set_seed0(PG_FUNCTION_ARGS)
{
	LegacyKeys keys = decode_keys(PG_GETARG_ARRAYTYPE_P(0));
	LegacySet *set = new_set();
	int i;
	CHECK_FOR_INTERRUPTS();
	for (i = 0; i < keys.count; i++)
		add_key(set, keys.ordered[i]);
	PG_RETURN_ARRAYTYPE_P(set_array(set));
}

Datum
contextbase_cpython311_union_seed0(PG_FUNCTION_ARGS)
{
	LegacySet *a = from_dictionary(decode_keys(PG_GETARG_ARRAYTYPE_P(0)));
	LegacySet *b = from_dictionary(decode_keys(PG_GETARG_ARRAYTYPE_P(1)));
	LegacySet *c = from_dictionary(decode_keys(PG_GETARG_ARRAYTYPE_P(2)));
	LegacySet *ab;
	CHECK_FOR_INTERRUPTS();
	ab = set_union(a, b);
	PG_RETURN_ARRAYTYPE_P(set_array(set_union(ab, c)));
}
