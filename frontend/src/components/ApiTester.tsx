"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, CheckCircle2, XCircle, Send, Code, Eye } from "lucide-react";

// Try port 5000 first, fallback to 5001
const API_PORTS = [5000, 5001];
let API_BASE_URL = `http://localhost:${API_PORTS[0]}`;

// Function to test API availability and set the correct port
async function findAvailableApi(): Promise<string> {
  for (const port of API_PORTS) {
    try {
      const url = `http://localhost:${port}/health`;
      const response = await fetch(url, {
        method: "GET",
        signal: AbortSignal.timeout(1000), // 1 second timeout
      });
      if (response.ok) {
        return `http://localhost:${port}`;
      }
    } catch (error) {
      continue;
    }
  }
  return `http://localhost:${API_PORTS[0]}`; // Default to 5000
}

interface ApiResponse {
  status: "success" | "error";
  data?: any;
  error?: string;
}

export default function ApiTester() {
  const [activeTab, setActiveTab] = useState("test-connection");
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<ApiResponse | null>(null);

  // Test Connection State
  const [subdomain, setSubdomain] = useState("");
  const [email, setEmail] = useState("");
  const [apiKey, setApiKey] = useState("");

  // Event Categories State
  const [selectedCategory, setSelectedCategory] = useState("");
  const [categories, setCategories] = useState<any[]>([]);

  // Create Webhook State - Single selection workflow
  const [webhookName, setWebhookName] = useState("");
  const [webhookEndpoint, setWebhookEndpoint] = useState("");
  const [webhookSubdomain, setWebhookSubdomain] = useState("");
  const [webhookEmail, setWebhookEmail] = useState("");
  const [webhookApiKey, setWebhookApiKey] = useState("");

  // Single selection states for webhook creation
  const [selectedWebhookCategory, setSelectedWebhookCategory] = useState("");
  const [webhookCategoryEvents, setWebhookCategoryEvents] = useState<any[]>([]);
  const [selectedWebhookEvent, setSelectedWebhookEvent] = useState("");
  const [selectedSubscription, setSelectedSubscription] = useState("");

  // Multi-selection states for Events tab (display purposes)
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [categoryEvents, setCategoryEvents] = useState<any>({});
  const [selectedEventTypes, setSelectedEventTypes] = useState<string[]>([]);

  const [authType, setAuthType] = useState<string>("none");
  const [authData, setAuthData] = useState<any>({});

  const resetResponse = () => {
    setResponse(null);
  };

  // Fetch events for selected webhook category
  const fetchWebhookCategoryEvents = async (category: string) => {
    try {
      API_BASE_URL = await findAvailableApi();
      const res = await fetch(`${API_BASE_URL}/zendesk/events/${category}`);
      const data = await res.json();

      if (res.ok) {
        setWebhookCategoryEvents(data.events || []);
        // Reset event and subscription selection when category changes
        setSelectedWebhookEvent("");
        setSelectedSubscription("");
      }
    } catch (error) {
      console.error(`Failed to fetch events for ${category}:`, error);
    }
  };

  // Handle category selection
  const handleCategoryChange = (category: string) => {
    setSelectedWebhookCategory(category);
    if (category) {
      fetchWebhookCategoryEvents(category);
    } else {
      setWebhookCategoryEvents([]);
      setSelectedWebhookEvent("");
      setSelectedSubscription("");
    }
  };

  // Handle event selection
  const handleEventChange = (eventValue: string) => {
    setSelectedWebhookEvent(eventValue);
    // When event changes, set it as the subscription
    setSelectedSubscription(eventValue);
  };

  // Fetch events for a specific category (for Events tab)
  const fetchCategoryEvents = async (category: string) => {
    if (categoryEvents[category]) {
      return; // Already fetched
    }

    try {
      API_BASE_URL = await findAvailableApi();
      const res = await fetch(`${API_BASE_URL}/zendesk/events/${category}`);
      const data = await res.json();

      if (res.ok) {
        setCategoryEvents((prev: any) => ({
          ...prev,
          [category]: data.events || [],
        }));
      }
    } catch (error) {
      console.error(`Failed to fetch events for ${category}:`, error);
    }
  };

  // Toggle category selection (for Events tab)
  const toggleCategorySelection = (category: string) => {
    setSelectedCategories((prev: string[]) => {
      const isSelected = prev.includes(category);
      if (isSelected) {
        // Remove category and its events
        const categoryEventValues =
          categoryEvents[category]?.map((e: any) => e.value) || [];
        setSelectedEventTypes((prevEvents: string[]) =>
          prevEvents.filter((e: string) => !categoryEventValues.includes(e))
        );
        return prev.filter((c: string) => c !== category);
      } else {
        // Add category and fetch its events
        fetchCategoryEvents(category);
        return [...prev, category];
      }
    });
  };

  // Toggle event type selection (for Events tab)
  const toggleEventTypeSelection = (eventValue: string) => {
    setSelectedEventTypes((prev: string[]) =>
      prev.includes(eventValue)
        ? prev.filter((e: string) => e !== eventValue)
        : [...prev, eventValue]
    );
  };

  const handleTestConnection = async () => {
    if (!subdomain || !email || !apiKey) {
      setResponse({
        status: "error",
        error: "Please fill in all fields",
      });
      return;
    }

    setLoading(true);
    resetResponse();

    try {
      // Find available API port
      API_BASE_URL = await findAvailableApi();

      const res = await fetch(`${API_BASE_URL}/zendesk/test-connection`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          subdomain,
          email,
          api_key: apiKey,
        }),
      });

      const data = await res.json();

      if (res.ok) {
        setResponse({
          status: "success",
          data,
        });
      } else {
        setResponse({
          status: "error",
          error: data.detail || "Connection failed",
        });
      }
    } catch (error: any) {
      setResponse({
        status: "error",
        error: error.message || "Failed to connect to API",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleGetCategories = async () => {
    setLoading(true);
    resetResponse();

    try {
      // Find available API port
      API_BASE_URL = await findAvailableApi();

      const res = await fetch(`${API_BASE_URL}/zendesk/event-categories`);
      const data = await res.json();

      if (res.ok) {
        setCategories(data.categories || []);
        setResponse({
          status: "success",
          data,
        });
      } else {
        setResponse({
          status: "error",
          error: data.detail || "Failed to fetch categories",
        });
      }
    } catch (error: any) {
      setResponse({
        status: "error",
        error: error.message || "Failed to connect to API",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleGetEventsByCategory = async () => {
    if (!selectedCategory) {
      setResponse({
        status: "error",
        error: "Please select a category",
      });
      return;
    }

    setLoading(true);
    resetResponse();

    try {
      // Find available API port
      API_BASE_URL = await findAvailableApi();

      const res = await fetch(
        `${API_BASE_URL}/zendesk/events/${selectedCategory}`
      );
      const data = await res.json();

      if (res.ok) {
        setResponse({
          status: "success",
          data,
        });
      } else {
        setResponse({
          status: "error",
          error: data.detail || "Failed to fetch events",
        });
      }
    } catch (error: any) {
      setResponse({
        status: "error",
        error: error.message || "Failed to connect to API",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleCreateWebhook = async () => {
    if (
      !webhookName ||
      !webhookEndpoint ||
      !webhookSubdomain ||
      !webhookEmail ||
      !webhookApiKey
    ) {
      setResponse({
        status: "error",
        error: "Please fill in all required fields",
      });
      return;
    }

    if (!selectedSubscription) {
      setResponse({
        status: "error",
        error: "Please select a category, then an event to create subscription",
      });
      return;
    }

    setLoading(true);
    resetResponse();

    try {
      API_BASE_URL = await findAvailableApi();

      const payload: any = {
        subdomain: webhookSubdomain,
        email: webhookEmail,
        api_key: webhookApiKey,
        name: webhookName,
        endpoint: webhookEndpoint,
        subscriptions: [selectedSubscription], // Single subscription
      };

      // Add authentication if selected
      if (authType !== "none") {
        if (authType === "api_key") {
          payload.authentication = {
            type: "api_key",
            data: {
              name: authData.name || "",
              value: authData.value || "",
            },
          };
        } else if (authType === "basic_auth") {
          payload.authentication = {
            type: "basic_auth",
            data: {
              username: authData.username || "",
              password: authData.password || "",
            },
          };
        } else if (authType === "bearer_token") {
          payload.authentication = {
            type: "bearer_token",
            data: {
              token: authData.token || "",
            },
          };
        }
      }

      const res = await fetch(`${API_BASE_URL}/zendesk/webhooks`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (res.ok) {
        setResponse({
          status: "success",
          data,
        });
      } else {
        setResponse({
          status: "error",
          error: data.detail || "Failed to create webhook",
        });
      }
    } catch (error: any) {
      setResponse({
        status: "error",
        error: error.message || "Failed to connect to API",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Left Panel - API Request */}
      <div>
        <Card className="border-slate-200 dark:border-slate-800">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Send className="w-5 h-5 text-blue-600" />
              API Request
            </CardTitle>
            <CardDescription>Configure and send API requests</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs
              value={activeTab}
              onValueChange={setActiveTab}
              className="w-full"
            >
              <TabsList className="grid w-full grid-cols-4">
                <TabsTrigger value="test-connection">
                  Test Connection
                </TabsTrigger>
                <TabsTrigger value="categories">Categories</TabsTrigger>
                <TabsTrigger value="events">Events</TabsTrigger>
                <TabsTrigger value="create-webhook">Create Webhook</TabsTrigger>
              </TabsList>

              {/* Test Connection Tab */}
              <TabsContent value="test-connection" className="space-y-4 mt-4">
                <div className="space-y-2">
                  <Label htmlFor="subdomain">Subdomain</Label>
                  <Input
                    id="subdomain"
                    placeholder="your-company"
                    value={subdomain}
                    onChange={(e) => setSubdomain(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="admin@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="apiKey">API Key</Label>
                  <Input
                    id="apiKey"
                    type="password"
                    placeholder="Enter your Zendesk API key"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                  />
                </div>

                <div className="pt-2">
                  <Button
                    onClick={handleTestConnection}
                    disabled={loading}
                    className="w-full"
                  >
                    {loading ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        Testing Connection...
                      </>
                    ) : (
                      <>
                        <Send className="w-4 h-4 mr-2" />
                        Test Connection
                      </>
                    )}
                  </Button>
                </div>

                <div className="mt-4 p-3 bg-slate-100 dark:bg-slate-900 rounded-md">
                  <p className="text-xs font-mono text-slate-600 dark:text-slate-400">
                    POST /zendesk/test-connection
                  </p>
                </div>
              </TabsContent>

              {/* Event Categories Tab */}
              <TabsContent value="categories" className="space-y-4 mt-4">
                <Alert>
                  <Eye className="h-4 w-4" />
                  <AlertDescription>
                    Get all Zendesk event categories with event counts
                  </AlertDescription>
                </Alert>

                <Button
                  onClick={handleGetCategories}
                  disabled={loading}
                  className="w-full"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Fetching Categories...
                    </>
                  ) : (
                    <>
                      <Send className="w-4 h-4 mr-2" />
                      Get Event Categories
                    </>
                  )}
                </Button>

                <div className="mt-4 p-3 bg-slate-100 dark:bg-slate-900 rounded-md">
                  <p className="text-xs font-mono text-slate-600 dark:text-slate-400">
                    GET /zendesk/event-categories
                  </p>
                </div>
              </TabsContent>

              {/* Events by Category Tab */}
              <TabsContent value="events" className="space-y-4 mt-4">
                <div className="space-y-2">
                  <Label htmlFor="category">Select Category</Label>
                  <Select
                    value={selectedCategory}
                    onValueChange={setSelectedCategory}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Choose a category" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ticket">Ticket Events</SelectItem>
                      <SelectItem value="user">User Events</SelectItem>
                      <SelectItem value="organization">
                        Organization Events
                      </SelectItem>
                      <SelectItem value="article">Article Events</SelectItem>
                      <SelectItem value="community">
                        Community Events
                      </SelectItem>
                      <SelectItem value="agent_availability">
                        Agent Availability
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Button
                  onClick={handleGetEventsByCategory}
                  disabled={loading || !selectedCategory}
                  className="w-full"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Fetching Events...
                    </>
                  ) : (
                    <>
                      <Send className="w-4 h-4 mr-2" />
                      Get Events
                    </>
                  )}
                </Button>

                <div className="mt-4 p-3 bg-slate-100 dark:bg-slate-900 rounded-md">
                  <p className="text-xs font-mono text-slate-600 dark:text-slate-400">
                    GET /zendesk/events/{selectedCategory || "{category}"}
                  </p>
                </div>
              </TabsContent>

              {/* Create Webhook Tab */}
              <TabsContent value="create-webhook" className="space-y-4 mt-4">
                <Alert>
                  <Eye className="h-4 w-4" />
                  <AlertDescription>
                    Create a webhook: Select 1 category → 1 event → creates 1
                    subscription
                  </AlertDescription>
                </Alert>

                <div className="space-y-2">
                  <Label htmlFor="webhook-subdomain">Subdomain *</Label>
                  <Input
                    id="webhook-subdomain"
                    placeholder="your-company"
                    value={webhookSubdomain}
                    onChange={(e) => setWebhookSubdomain(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="webhook-email">Email *</Label>
                  <Input
                    id="webhook-email"
                    type="email"
                    placeholder="admin@company.com"
                    value={webhookEmail}
                    onChange={(e) => setWebhookEmail(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="webhook-api-key">API Key *</Label>
                  <Input
                    id="webhook-api-key"
                    type="password"
                    placeholder="Your Zendesk API key"
                    value={webhookApiKey}
                    onChange={(e) => setWebhookApiKey(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="webhook-name">Webhook Name *</Label>
                  <Input
                    id="webhook-name"
                    placeholder="My Production Webhook"
                    value={webhookName}
                    onChange={(e) => setWebhookName(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="webhook-endpoint">Endpoint URL *</Label>
                  <Input
                    id="webhook-endpoint"
                    placeholder="https://your-server.com/webhooks/zendesk"
                    value={webhookEndpoint}
                    onChange={(e) => setWebhookEndpoint(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="webhook-category">
                    Step 1: Select Category *
                  </Label>
                  <Select
                    value={selectedWebhookCategory}
                    onValueChange={handleCategoryChange}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Choose a category" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ticket">
                        Ticket Events (50+ events)
                      </SelectItem>
                      <SelectItem value="user">
                        User Events (20+ events)
                      </SelectItem>
                      <SelectItem value="organization">
                        Organization Events
                      </SelectItem>
                      <SelectItem value="article">Article Events</SelectItem>
                      <SelectItem value="community">
                        Community Events
                      </SelectItem>
                      <SelectItem value="agent_availability">
                        Agent Availability
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  {selectedWebhookCategory && (
                    <p className="text-xs text-green-600 mt-1">
                      ✓ Category selected: {selectedWebhookCategory}
                    </p>
                  )}
                </div>

                {selectedWebhookCategory &&
                  webhookCategoryEvents.length > 0 && (
                    <div className="space-y-2">
                      <Label htmlFor="webhook-event">
                        Step 2: Select Event *
                      </Label>
                      <Select
                        value={selectedWebhookEvent}
                        onValueChange={handleEventChange}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Choose an event from this category" />
                        </SelectTrigger>
                        <SelectContent className="max-h-64">
                          {webhookCategoryEvents.map((event: any) => (
                            <SelectItem key={event.value} value={event.value}>
                              <div className="flex flex-col">
                                <span className="font-medium">
                                  {event.label}
                                </span>
                                <span className="text-xs text-slate-500">
                                  {event.description}
                                </span>
                              </div>
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {selectedWebhookEvent && (
                        <p className="text-xs text-green-600 mt-1">
                          ✓ Event selected:{" "}
                          {
                            webhookCategoryEvents.find(
                              (e) => e.value === selectedWebhookEvent
                            )?.label
                          }
                        </p>
                      )}
                    </div>
                  )}

                {selectedSubscription && (
                  <div className="p-3 bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-md">
                    <p className="text-xs text-blue-800 dark:text-blue-200">
                      <strong>Subscription:</strong>{" "}
                      {webhookCategoryEvents.find(
                        (e) => e.value === selectedSubscription
                      )?.label || selectedSubscription}
                    </p>
                    <p className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                      Category: {selectedWebhookCategory}
                    </p>
                  </div>
                )}

                <div className="space-y-2">
                  <Label htmlFor="auth-type">Authentication (Optional)</Label>
                  <Select value={authType} onValueChange={setAuthType}>
                    <SelectTrigger>
                      <SelectValue placeholder="No Authentication" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">No Authentication</SelectItem>
                      <SelectItem value="api_key">API Key</SelectItem>
                      <SelectItem value="basic_auth">Basic Auth</SelectItem>
                      <SelectItem value="bearer_token">Bearer Token</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {authType === "api_key" && (
                  <div className="space-y-2 pl-4 border-l-2">
                    <div className="space-y-2">
                      <Label>Header Name</Label>
                      <Input
                        placeholder="X-API-Key"
                        value={authData.name || ""}
                        onChange={(e) =>
                          setAuthData({ ...authData, name: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Header Value</Label>
                      <Input
                        type="password"
                        placeholder="your-api-key"
                        value={authData.value || ""}
                        onChange={(e) =>
                          setAuthData({ ...authData, value: e.target.value })
                        }
                      />
                    </div>
                  </div>
                )}

                {authType === "basic_auth" && (
                  <div className="space-y-2 pl-4 border-l-2">
                    <div className="space-y-2">
                      <Label>Username</Label>
                      <Input
                        placeholder="username"
                        value={authData.username || ""}
                        onChange={(e) =>
                          setAuthData({ ...authData, username: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Password</Label>
                      <Input
                        type="password"
                        placeholder="password"
                        value={authData.password || ""}
                        onChange={(e) =>
                          setAuthData({ ...authData, password: e.target.value })
                        }
                      />
                    </div>
                  </div>
                )}

                {authType === "bearer_token" && (
                  <div className="space-y-2 pl-4 border-l-2">
                    <Label>Token</Label>
                    <Input
                      type="password"
                      placeholder="your-bearer-token"
                      value={authData.token || ""}
                      onChange={(e) =>
                        setAuthData({ ...authData, token: e.target.value })
                      }
                    />
                  </div>
                )}

                <Button
                  onClick={handleCreateWebhook}
                  disabled={loading}
                  className="w-full"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Creating Webhook...
                    </>
                  ) : (
                    <>
                      <Send className="w-4 h-4 mr-2" />
                      Create Webhook
                    </>
                  )}
                </Button>

                <div className="mt-4 p-3 bg-slate-100 dark:bg-slate-900 rounded-md">
                  <p className="text-xs font-mono text-slate-600 dark:text-slate-400">
                    POST /zendesk/webhooks
                  </p>
                </div>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>

      {/* Right Panel - API Response */}
      <div>
        <Card className="border-slate-200 dark:border-slate-800 h-full">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Code className="w-5 h-5 text-purple-600" />
              Response
            </CardTitle>
            <CardDescription>API response will appear here</CardDescription>
          </CardHeader>
          <CardContent>
            {response ? (
              <div className="space-y-4">
                {/* Status Badge */}
                <div className="flex items-center gap-2">
                  {response.status === "success" ? (
                    <>
                      <CheckCircle2 className="w-5 h-5 text-green-600" />
                      <Badge variant="default" className="bg-green-600">
                        Success
                      </Badge>
                    </>
                  ) : (
                    <>
                      <XCircle className="w-5 h-5 text-red-600" />
                      <Badge variant="destructive">Error</Badge>
                    </>
                  )}
                </div>

                {/* Response Body */}
                {response.status === "success" && response.data && (
                  <div className="rounded-lg bg-slate-950 p-4 overflow-auto max-h-[600px]">
                    <pre className="text-xs text-green-400 font-mono">
                      {JSON.stringify(response.data, null, 2)}
                    </pre>
                  </div>
                )}

                {response.status === "error" && (
                  <Alert variant="destructive">
                    <XCircle className="h-4 w-4" />
                    <AlertDescription>
                      {typeof response.error === "string"
                        ? response.error
                        : JSON.stringify(response.error, null, 2)}
                    </AlertDescription>
                  </Alert>
                )}

                {/* Clear Button */}
                <Button
                  variant="outline"
                  onClick={resetResponse}
                  className="w-full"
                >
                  Clear Response
                </Button>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-64 text-slate-400">
                <Code className="w-16 h-16 mb-4 opacity-20" />
                <p className="text-sm">No response yet</p>
                <p className="text-xs mt-1">
                  Send a request to see the response
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
