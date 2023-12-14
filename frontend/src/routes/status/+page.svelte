<script lang="ts">
	import { convertPlexDebridItemsToObject, formatState } from '$lib/helpers';
	import { invalidateAll } from '$app/navigation';
	import { Button } from '$lib/components/ui/button';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import * as Accordion from '$lib/components/ui/accordion';
	import { Loader2, ArrowUpRight, RotateCw, Info } from 'lucide-svelte';
	import StatusMediaCard from '$lib/components/status-media-card.svelte';
	import { toast } from 'svelte-sonner';
	import type { StatusInfo } from '$lib/types';

	export let data;

	let reloadButtonLoading = false;

	async function reloadData() {
		reloadButtonLoading = true;
		await invalidateAll();
		reloadButtonLoading = false;
		toast.success('Refreshed data');
	}

	const statusInfo: StatusInfo = {
		ERROR: {
			text: formatState('ERROR'),
			color: 'text-red-500',
			bg: 'bg-red-500',
			description: 'Error occurred during processing'
		},
		UNKNOWN: {
			text: formatState('UNKNOWN'),
			color: 'text-red-500',
			bg: 'bg-red-500',
			description: 'Unknown status'
		},
		LIBRARY: {
			text: 'In Library',
			color: 'text-green-400',
			bg: 'bg-green-400',
			description: 'Item is in your library'
		},
		LIBRARY_ONGOING: {
			text: formatState('LIBRARY_ONGOING'),
			color: 'text-green-400',
			bg: 'bg-green-400',
			description: 'Item is in your library and is ongoing'
		},
		LIBRARY_METADATA: {
			text: formatState('LIBRARY_METADATA'),
			color: 'text-gray-500',
			bg: 'bg-gray-500',
			description: 'TODO: Add description'
		},
		CONTENT: {
			text: 'Requested',
			color: 'text-purple-500',
			bg: 'bg-purple-500',
			description: 'Item is requested from external service'
		},
		SCRAPED: {
			text: formatState('SCRAPED'),
			color: 'text-yellow-500',
			bg: 'bg-yellow-500',
			description: 'Item is scraped and will be downloaded'
		},
		SCRAPED_NOT_FOUND: {
			text: formatState('SCRAPED_NOT_FOUND'),
			color: 'text-red-500',
			bg: 'bg-red-500',
			description: 'Item was unable to be scraped'
		},
		PARTIALLY_SCRAPED: {
			text: formatState('PARTIALLY_SCRAPED'),
			color: 'text-yellow-500',
			bg: 'bg-yellow-500',
			description: 'Item was partially scraped'
		},
		DOWNLOADING: {
			text: formatState('DOWNLOADING'),
			color: 'text-yellow-500',
			bg: 'bg-yellow-500',
			description: 'Item is currently downloading'
		},
		PARTIALLY_DOWNLOADING: {
			text: formatState('PARTIALLY_DOWNLOADING'),
			color: 'text-yellow-500',
			bg: 'bg-yellow-500',
			description: 'Item is partially downloading'
		}
	};
</script>

<svelte:head>
	<title>Iceberg | Status</title>
</svelte:head>

<div class="flex flex-col gap-2 p-8 md:px-24 lg:px-32">
	{#await data.streamed.items}
		<div class="flex items-center gap-1 w-full justify-center">
			<Loader2 class="animate-spin w-4 h-4" />
			<p class="text-lg text-muted-foreground">Loading library items...</p>
		</div>
	{:then items}
		<div class="flex flex-row items-center justify-between">
			<div class="flex flex-col items-start">
				<h1 class="text-3xl md:text-4xl font-semibold">
					Status <span class="text-xl md:text-2xl">({items.items.length})</span>
				</h1>
				<p class="md:text-lg text-muted-foreground">
					This page shows the status of your library items.
				</p>
			</div>
			<div class="flex flex-row items-center gap-2">
				<Tooltip.Root>
					<Tooltip.Trigger asChild let:builder>
						<Button
							builders={[builder]}
							disabled={reloadButtonLoading}
							type="button"
							variant="outline"
							size="sm"
							class="max-w-max"
							on:click={reloadData}
						>
							<RotateCw class="h-4 w-4" />
						</Button>
					</Tooltip.Trigger>
					<Tooltip.Content>
						<p>Reload data</p>
					</Tooltip.Content>
				</Tooltip.Root>

				<Tooltip.Root>
					<Tooltip.Trigger asChild let:builder>
						<Button
							builders={[builder]}
							variant="outline"
							size="sm"
							class="max-w-max"
							href="https://app.plex.tv/desktop"
						>
							<ArrowUpRight class="h-4 w-4" />
						</Button>
					</Tooltip.Trigger>
					<Tooltip.Content>
						<p>Open Plex</p>
					</Tooltip.Content>
				</Tooltip.Root>
			</div>
		</div>

		<Accordion.Root>
			<Accordion.Item value="item-1">
				<Accordion.Trigger>
					<div class="flex items-center gap-2 md:text-lg">
						<Info class="h-4 w-4" />
						<p>Learn more about status badges</p>
					</div>
				</Accordion.Trigger>
				<Accordion.Content>
					<ul class="list-disc list-inside md:text-lg">
						{#each Object.keys(statusInfo) as key (key)}
							{#if key !== 'ERROR' && key !== 'UNKNOWN'}
								<li>
									<span class="font-semibold {statusInfo[key].color}">{statusInfo[key].text}:</span>
									{statusInfo[key].description}
								</li>
							{/if}
						{/each}
					</ul>
				</Accordion.Content>
			</Accordion.Item>
		</Accordion.Root>
		{@const plexDebridItems = convertPlexDebridItemsToObject(items.items)}
		{#each Object.keys(plexDebridItems) as key (key)}
			<div class="flex flex-col gap-4">
				{#each plexDebridItems[key] as item}
					<StatusMediaCard plexDebridItem={item} itemState={statusInfo[item.state]} />
				{/each}
			</div>
		{/each}
	{:catch error}
		<p>{error.message}</p>
	{/await}
</div>