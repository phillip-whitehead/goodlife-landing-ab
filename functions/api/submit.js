/**
 * Cloudflare Pages Function: /api/submit
 * Handles landing page inquiry form submissions.
 * Creates/updates HubSpot contact with A/B version tracking.
 *
 * Environment variables required (set in Cloudflare Pages dashboard):
 *   HUBSPOT_TOKEN  — private app access token
 */

export async function onRequestPost(context) {
  const { request, env } = context;

  // CORS headers for same-origin form posts
  const corsHeaders = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  try {
    const body = await request.json();
    const { firstname, email, gl_version, page_url, referrer } = body;

    if (!email || !email.includes('@')) {
      return Response.json({ success: false, error: 'Valid email required' }, { status: 400, headers: corsHeaders });
    }

    const token = env.HUBSPOT_TOKEN;
    if (!token) {
      return Response.json({ success: false, error: 'Server config error' }, { status: 500, headers: corsHeaders });
    }

    const contactProps = {
      firstname: firstname || '',
      email: email.toLowerCase().trim(),
      gl_ab_version: gl_version || 'direct',
      hs_analytics_source: 'DIRECT_TRAFFIC',
      lifecyclestage: 'lead',
    };

    // Try to create contact
    let hubRes = await fetch('https://api.hubapi.com/crm/v3/objects/contacts', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ properties: contactProps }),
    });

    // If contact already exists (409), find and update by email
    if (hubRes.status === 409) {
      // Search for existing contact
      const searchRes = await fetch('https://api.hubapi.com/crm/v3/objects/contacts/search', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          filterGroups: [{
            filters: [{ propertyName: 'email', operator: 'EQ', value: email.toLowerCase().trim() }]
          }],
          properties: ['email', 'gl_ab_version'],
          limit: 1,
        }),
      });

      const searchData = await searchRes.json();
      if (searchData.results && searchData.results.length > 0) {
        const contactId = searchData.results[0].id;
        // Update existing — only set gl_ab_version if not already set
        const existingVersion = searchData.results[0].properties?.gl_ab_version;
        const updateProps = { ...contactProps };
        if (existingVersion) delete updateProps.gl_ab_version; // preserve first-touch version

        hubRes = await fetch(`https://api.hubapi.com/crm/v3/objects/contacts/${contactId}`, {
          method: 'PATCH',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ properties: updateProps }),
        });
      }
    }

    const hubData = await hubRes.json();

    if (!hubRes.ok && hubRes.status !== 409) {
      console.error('HubSpot error:', JSON.stringify(hubData));
      return Response.json({ success: false, error: 'CRM error' }, { status: 500, headers: corsHeaders });
    }

    return Response.json({ success: true, version: gl_version || 'direct' }, { headers: corsHeaders });

  } catch (err) {
    console.error('Submit error:', err.message);
    return Response.json({ success: false, error: 'Server error' }, { status: 500, headers: corsHeaders });
  }
}

export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    },
  });
}
