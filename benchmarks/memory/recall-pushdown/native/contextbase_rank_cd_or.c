/*
 * Exact specialization of PostgreSQL's two-argument ts_rank_cd for plain OR.
 *
 * In tsrank.c, every minimal cover of an unweighted, non-prefix OR query is
 * one matching lexeme occurrence.  Thus no document-position sort or repeated
 * query-tree execution is needed.  Duplicate query operands count once, as in
 * get_docrep().  The four default float4 weights are exact binary values;
 * with this bounded query size their sum fits exactly in float8, so changing
 * accumulation order does not change the final float4.  Other query shapes
 * delegate to the original function, including phrase, AND, NOT and prefixes.
 *
 * This is a per-expression query cache, not a cache of documents, scores or
 * benchmark answers.  No memory survives the expression's memory context.
 */
#include "postgres.h"
#include "fmgr.h"
#include "miscadmin.h"
#include "varatt.h"
#include "tsearch/ts_utils.h"
#include "utils/fmgrprotos.h"
#include "utils/memutils.h"

PG_MODULE_MAGIC;
PG_FUNCTION_INFO_V1(contextbase_rank_cd_or);

#define MAX_FAST_QUERY_ITEMS 256

typedef struct CachedLexeme
{
	int			length;
	int			distance;
} CachedLexeme;

typedef struct RankQueryCache
{
	MemoryContext context;
	TSQuery		query;
	CachedLexeme *terms;
	int			nterms;
	bool		eligible;
} RankQueryCache;

static void
prepare_query(RankQueryCache *cache, TSQuery query)
{
	MemoryContext oldcontext;
	QueryItem  *items;
	int			i;

	MemoryContextReset(cache->context);
	/* A caught allocation error must not leave a pointer to the old query. */
	cache->query = NULL;
	oldcontext = MemoryContextSwitchTo(cache->context);
	cache->query = palloc(VARSIZE(query));
	memcpy(cache->query, query, VARSIZE(query));
	cache->nterms = 0;
	cache->terms = NULL;
	cache->eligible = query->size > 0 && query->size <= MAX_FAST_QUERY_ITEMS;
	if (!cache->eligible)
	{
		MemoryContextSwitchTo(oldcontext);
		return;
	}
	cache->terms = palloc_array(CachedLexeme, query->size);
	items = GETQUERY(cache->query);
	for (i = 0; i < query->size; i++)
	{
		QueryOperand *operand;
		int			j;
		bool		duplicate = false;

		if (items[i].type == QI_OPR && items[i].qoperator.oper == OP_OR)
			continue;
		if (items[i].type != QI_VAL || items[i].qoperand.prefix ||
			items[i].qoperand.weight != 0)
		{
			cache->eligible = false;
			break;
		}
		operand = &items[i].qoperand;
		for (j = 0; j < cache->nterms; j++)
		{
			CachedLexeme *term = &cache->terms[j];

			if (term->length == operand->length &&
				memcmp(GETOPERAND(cache->query) + term->distance,
					   GETOPERAND(cache->query) + operand->distance,
					   term->length) == 0)
			{
				duplicate = true;
				break;
			}
		}
		if (!duplicate)
		{
			cache->terms[cache->nterms].length = operand->length;
			cache->terms[cache->nterms].distance = operand->distance;
			cache->nterms++;
		}
	}
	MemoryContextSwitchTo(oldcontext);
}

Datum
contextbase_rank_cd_or(PG_FUNCTION_ARGS)
{
	TSVector	vector = PG_GETARG_TSVECTOR(0);
	TSQuery		query = PG_GETARG_TSQUERY(1);
	RankQueryCache *cache = fcinfo->flinfo->fn_extra;
	static const float4 weights[4] = {0.1f, 0.2f, 0.4f, 1.0f};
	double		score = 0.0;
	int			i;

	if (cache == NULL)
	{
		MemoryContext oldcontext = MemoryContextSwitchTo(fcinfo->flinfo->fn_mcxt);

		cache = palloc0(sizeof(RankQueryCache));
		cache->context = AllocSetContextCreate(fcinfo->flinfo->fn_mcxt,
											 "OR rank query cache",
											 ALLOCSET_SMALL_SIZES);
		fcinfo->flinfo->fn_extra = cache;
		MemoryContextSwitchTo(oldcontext);
	}
	if (cache->query == NULL || VARSIZE(cache->query) != VARSIZE(query) ||
		memcmp(cache->query, query, VARSIZE(query)) != 0)
		prepare_query(cache, query);

	if (!cache->eligible)
	{
		Datum result = DirectFunctionCall2(ts_rankcd_tt,
										  PointerGetDatum(vector), PointerGetDatum(query));

		PG_FREE_IF_COPY(vector, 0);
		PG_FREE_IF_COPY(query, 1);
		PG_RETURN_DATUM(result);
	}
	for (i = 0; i < cache->nterms; i++)
	{
		CachedLexeme *term = &cache->terms[i];
		char	   *lexeme = GETOPERAND(cache->query) + term->distance;
		int			low = 0;
		int			high = vector->size;

		CHECK_FOR_INTERRUPTS();
		while (low < high)
		{
			int			mid = low + (high - low) / 2;
			WordEntry  *entry = ARRPTR(vector) + mid;
			int			comparison = tsCompareString(lexeme, term->length,
													 STRPTR(vector) + entry->pos,
													 entry->len, false);

			if (comparison < 0)
				high = mid;
			else if (comparison > 0)
				low = mid + 1;
			else
			{
				if (entry->haspos)
				{
					WordEntryPos *positions = POSDATAPTR(vector, entry);
					int			count = POSDATALEN(vector, entry);
					int			j;

					for (j = 0; j < count; j++)
						score += (double) weights[WEP_GETWEIGHT(positions[j])];
				}
				break;
			}
		}
	}
	PG_FREE_IF_COPY(vector, 0);
	PG_FREE_IF_COPY(query, 1);
	PG_RETURN_FLOAT4((float4) score);
}
