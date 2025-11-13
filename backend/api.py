"""
FlowGenX AI - Unified Webhook Automation System
Enterprise-grade webhook receiver for Zendesk and HubSpot
with comprehensive security, monitoring, and async processing
"""

from fastapi import FastAPI, HTTPException, Request, Header, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, AnyUrl, EmailStr, Field, validator
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime, timedelta
from enum import Enum
import requests
import base64
import json
import hmac
import hashlib
import logging
import asyncio
from urllib.parse import unquote
import redis.asyncio as redis
from contextlib import asynccontextmanager

# ============================================================================
# Configuration & Setup
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Redis for idempotency and rate limiting
REDIS_URL = "redis://localhost:6379"
redis_client: Optional[redis.Redis] = None

# Circuit breaker configuration
CIRCUIT_BREAKER_ERROR_THRESHOLD = 0.7  # 70% error rate
CIRCUIT_BREAKER_MIN_REQUESTS = 100
CIRCUIT_BREAKER_TIME_WINDOW = 300  # 5 minutes

# Webhook timeout configurations
HUBSPOT_TIMEOUT = 5  # seconds
ZENDESK_TIMEOUT = 12  # seconds
TIMESTAMP_MAX_AGE = 300000  # 5 minutes in milliseconds

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for Redis connection"""
    global redis_client
    redis_client = await redis.from_url(REDIS_URL, decode_responses=True)
    logger.info("Redis connection established")
    yield
    await redis_client.close()
    logger.info("Redis connection closed")

app = FastAPI(
    title="FlowGenX AI - Unified Webhook System",
    description="Enterprise webhook receiver for Zendesk and HubSpot with security and monitoring",
    version="2.0.0",
    lifespan=lifespan
)

# ============================================================================
# Enums & Models
# ============================================================================

class PlatformType(str, Enum):
    ZENDESK = "zendesk"
    HUBSPOT = "hubspot"

class ConnectionStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    
class WebhookStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

# ============================================================================
# Zendesk Models
# ============================================================================

class ZendeskAuthType(str, Enum):
    API_KEY = "api_key"
    BASIC_AUTH = "basic_auth"
    BEARER_TOKEN = "bearer_token"

class ZendeskAuthentication(BaseModel):
    type: ZendeskAuthType
    data: Dict[str, str]
    
    @validator('data')
    def validate_auth_data(cls, v, values):
        auth_type = values.get('type')
        if auth_type == ZendeskAuthType.API_KEY:
            if 'name' not in v or 'value' not in v:
                raise ValueError("API key requires 'name' and 'value'")
        elif auth_type == ZendeskAuthType.BASIC_AUTH:
            if 'username' not in v or 'password' not in v:
                raise ValueError("Basic auth requires 'username' and 'password'")
        elif auth_type == ZendeskAuthType.BEARER_TOKEN:
            if 'token' not in v:
                raise ValueError("Bearer token requires 'token'")
        return v

class ZendeskTestConnection(BaseModel):
    subdomain: str
    email: EmailStr
    api_key: str

class ZendeskCreateWebhook(BaseModel):
    subdomain: str
    email: EmailStr
    api_key: str
    name: str
    endpoint: AnyUrl
    subscriptions: List[str]
    authentication: Optional[ZendeskAuthentication] = None
    custom_headers: Optional[Dict[str, str]] = None
    
    @validator('custom_headers')
    def validate_headers(cls, v):
        if v and len(v) > 5:
            raise ValueError("Maximum 5 custom headers allowed")
        if v:
            for name, value in v.items():
                if len(name) > 128:
                    raise ValueError(f"Header name '{name}' exceeds 128 characters")
                if len(value) > 1000:
                    raise ValueError(f"Header value for '{name}' exceeds 1000 characters")
        return v

class ZendeskEventCategory(BaseModel):
    key: str
    name: str
    description: str
    count: int

class ZendeskEventType(BaseModel):
    value: str
    label: str
    description: str
    category: str

# ============================================================================
# HubSpot Models
# ============================================================================

class HubSpotEventType(BaseModel):
    object_type: str
    event_types: List[str]
    scope_required: str

class HubSpotTestConnection(BaseModel):
    """Test HubSpot API connection"""
    access_token: str  # Private app token or OAuth token

class HubSpotSubscription(BaseModel):
    """HubSpot webhook subscription details"""
    subscription_type: str  # e.g., "contact.creation", "deal.propertyChange"
    property_name: Optional[str] = None  # Required for propertyChange events
    
    class Config:
        schema_extra = {
            "example": {
                "subscription_type": "contact.creation",
                "property_name": None
            }
        }

class HubSpotCreateWebhook(BaseModel):
    """
    Create HubSpot webhook (Public OAuth App only)
    Requires DEVELOPER API KEY from HubSpot Developer Portal
    """
    app_id: str
    developer_api_key: str  # Developer Hapikey - NOT OAuth access token
    endpoint_url: str
    subscriptions: List[HubSpotSubscription]
    
    # class Config:
    #     schema_extra = {
    #         "example": {
    #             "app_id": "12345678",
    #             "developer_api_key": "your-developer-api-key",
    #             "endpoint_url": "https://your-server.com/webhook/hubspot",
    #             "subscriptions": [
    #                 {
    #                     "subscription_type": "contact.creation",
    #                     "property_name": None
    #                 },
    #                 {
    #                     "subscription_type": "contact.propertyChange", 
    #                     "property_name": "email"
    #                 },
    #                 {
    #                     "subscription_type": "deal.creation",
    #                     "property_name": None
    #                 }
    #             ]
    #         }
    #     }

class HubSpotWebhookResponse(BaseModel):
    """HubSpot webhook creation response"""
    success: bool
    subscription_ids: List[str]
    signing_secrets: Optional[Dict[str, str]] = {}
    webhook_url: str
    total_subscriptions: int
    message: str

# ============================================================================
# Zendesk Event Manager (Comprehensive List)
# ============================================================================

class ZendeskEventManager:
    """
    Complete Zendesk webhook event types across all domains
    90+ events covering tickets, users, organizations, articles, and agent availability
    """
    
    EVENT_TYPES = {
        "ticket": {
            "name": "Ticket Events",
            "description": "Comprehensive ticket lifecycle and update events",
            "events": [
                # Core ticket events
                {"value": "zen:event-type:ticket.created", "label": "Ticket Created", "description": "New ticket created in the system"},
                {"value": "zen:event-type:ticket.updated", "label": "Ticket Updated", "description": "Any ticket field updated"},
                {"value": "zen:event-type:ticket.solved", "label": "Ticket Solved", "description": "Ticket marked as solved"},
                {"value": "zen:event-type:ticket.closed", "label": "Ticket Closed", "description": "Ticket moved to closed status"},
                {"value": "zen:event-type:ticket.deleted", "label": "Ticket Deleted", "description": "Ticket permanently deleted"},
                
                # Status and assignment
                {"value": "zen:event-type:ticket.status_changed", "label": "Status Changed", "description": "Ticket status modified"},
                {"value": "zen:event-type:ticket.assigned", "label": "Ticket Assigned", "description": "Ticket assigned to agent"},
                {"value": "zen:event-type:ticket.assignee_changed", "label": "Assignee Changed", "description": "Ticket reassigned"},
                {"value": "zen:event-type:ticket.group_changed", "label": "Group Changed", "description": "Ticket group modified"},
                
                # Comments and interactions
                {"value": "zen:event-type:ticket.comment_added", "label": "Comment Added", "description": "New comment on ticket"},
                {"value": "zen:event-type:ticket.comment_made_public", "label": "Comment Public", "description": "Private comment made public"},
                {"value": "zen:event-type:ticket.comment_made_private", "label": "Comment Private", "description": "Public comment made private"},
                
                # Priority and tags
                {"value": "zen:event-type:ticket.priority_changed", "label": "Priority Changed", "description": "Ticket priority updated"},
                {"value": "zen:event-type:ticket.tags_changed", "label": "Tags Changed", "description": "Ticket tags modified"},
                {"value": "zen:event-type:ticket.tag_added", "label": "Tag Added", "description": "New tag added"},
                {"value": "zen:event-type:ticket.tag_removed", "label": "Tag Removed", "description": "Tag removed"},
                
                # Custom fields
                {"value": "zen:event-type:ticket.custom_field_changed", "label": "Custom Field Changed", "description": "Custom field value updated"},
                
                # Satisfaction and SLA
                {"value": "zen:event-type:ticket.satisfaction_rating_added", "label": "CSAT Rating Added", "description": "Customer satisfaction rating submitted"},
                {"value": "zen:event-type:ticket.sla_policy_added", "label": "SLA Policy Added", "description": "SLA policy applied to ticket"},
                {"value": "zen:event-type:ticket.sla_policy_removed", "label": "SLA Policy Removed", "description": "SLA policy removed"},
                {"value": "zen:event-type:ticket.sla_breach", "label": "SLA Breach", "description": "SLA target breached"},
                
                # Collaboration and sharing
                {"value": "zen:event-type:ticket.shared", "label": "Ticket Shared", "description": "Ticket shared with external party"},
                {"value": "zen:event-type:ticket.follower_added", "label": "Follower Added", "description": "Agent added as follower"},
                {"value": "zen:event-type:ticket.follower_removed", "label": "Follower Removed", "description": "Agent removed as follower"},
                
                # Merge operations
                {"value": "zen:event-type:ticket.merged", "label": "Ticket Merged", "description": "Ticket merged into another"},
                
                # Conditional (for triggers/automations)
                {"value": "conditional_ticket_events", "label": "Conditional Ticket Events", "description": "Use with triggers/automations for custom conditions"},
                
                # Advanced ticket events
                {"value": "zen:event-type:ticket.brand_changed", "label": "Brand Changed", "description": "Ticket brand modified"},
                {"value": "zen:event-type:ticket.form_changed", "label": "Form Changed", "description": "Ticket form updated"},
                {"value": "zen:event-type:ticket.type_changed", "label": "Type Changed", "description": "Ticket type modified"},
                {"value": "zen:event-type:ticket.subject_changed", "label": "Subject Changed", "description": "Ticket subject updated"},
                {"value": "zen:event-type:ticket.description_changed", "label": "Description Changed", "description": "Ticket description modified"},
                {"value": "zen:event-type:ticket.requester_changed", "label": "Requester Changed", "description": "Ticket requester updated"},
                {"value": "zen:event-type:ticket.due_date_changed", "label": "Due Date Changed", "description": "Ticket due date modified"},
                {"value": "zen:event-type:ticket.external_id_changed", "label": "External ID Changed", "description": "External ID updated"},
                {"value": "zen:event-type:ticket.problem_changed", "label": "Problem Changed", "description": "Problem ticket reference updated"},
                {"value": "zen:event-type:ticket.collaboration_added", "label": "Collaboration Added", "description": "Collaboration established"},
                {"value": "zen:event-type:ticket.collaboration_removed", "label": "Collaboration Removed", "description": "Collaboration ended"},
                {"value": "zen:event-type:ticket.via_changed", "label": "Via Changed", "description": "Ticket channel changed"},
                {"value": "zen:event-type:ticket.attachment_added", "label": "Attachment Added", "description": "File attached to ticket"}
            ]
        },
        
        "user": {
            "name": "User Events",
            "description": "User account and profile management events",
            "events": [
                # Core user events
                {"value": "zen:event-type:user.created", "label": "User Created", "description": "New user account created"},
                {"value": "zen:event-type:user.updated", "label": "User Updated", "description": "User profile updated"},
                {"value": "zen:event-type:user.deleted", "label": "User Deleted", "description": "User account deleted"},
                
                # Identity and authentication
                {"value": "zen:event-type:user.identity_created", "label": "Identity Created", "description": "New identity added to user"},
                {"value": "zen:event-type:user.identity_deleted", "label": "Identity Deleted", "description": "Identity removed from user"},
                {"value": "zen:event-type:user.identity_changed", "label": "Identity Changed", "description": "Primary identity modified"},
                
                # Profile fields
                {"value": "zen:event-type:user.name_changed", "label": "Name Changed", "description": "User name updated"},
                {"value": "zen:event-type:user.email_changed", "label": "Email Changed", "description": "User email modified"},
                {"value": "zen:event-type:user.phone_changed", "label": "Phone Changed", "description": "User phone updated"},
                {"value": "zen:event-type:user.details_changed", "label": "Details Changed", "description": "User details modified"},
                {"value": "zen:event-type:user.notes_changed", "label": "Notes Changed", "description": "User notes updated"},
                {"value": "zen:event-type:user.alias_changed", "label": "Alias Changed", "description": "User alias modified"},
                {"value": "zen:event-type:user.locale_changed", "label": "Locale Changed", "description": "User locale updated"},
                {"value": "zen:event-type:user.time_zone_changed", "label": "Time Zone Changed", "description": "User timezone modified"},
                
                # Organization and groups
                {"value": "zen:event-type:user.organization_changed", "label": "Organization Changed", "description": "User organization updated"},
                {"value": "zen:event-type:user.group_membership_created", "label": "Group Membership Added", "description": "User added to group"},
                {"value": "zen:event-type:user.group_membership_deleted", "label": "Group Membership Removed", "description": "User removed from group"},
                
                # Roles and permissions
                {"value": "zen:event-type:user.role_changed", "label": "Role Changed", "description": "User role modified"},
                {"value": "zen:event-type:user.custom_role_changed", "label": "Custom Role Changed", "description": "Custom role updated"},
                
                # Status and access
                {"value": "zen:event-type:user.suspended", "label": "User Suspended", "description": "User account suspended"},
                {"value": "zen:event-type:user.unsuspended", "label": "User Unsuspended", "description": "User account reactivated"},
                {"value": "zen:event-type:user.active_changed", "label": "Active Status Changed", "description": "User active status modified"},
                
                # Tags and custom fields
                {"value": "zen:event-type:user.tags_changed", "label": "Tags Changed", "description": "User tags modified"},
                {"value": "zen:event-type:user.custom_field_changed", "label": "Custom Field Changed", "description": "User custom field updated"},
                
                # External references
                {"value": "zen:event-type:user.external_id_changed", "label": "External ID Changed", "description": "External ID updated"},
                
                # Verification
                {"value": "zen:event-type:user.verified", "label": "User Verified", "description": "User verification status updated"}
            ]
        },
        
        "organization": {
            "name": "Organization Events",
            "description": "Organization management and update events",
            "events": [
                {"value": "zen:event-type:organization.created", "label": "Organization Created", "description": "New organization created"},
                {"value": "zen:event-type:organization.updated", "label": "Organization Updated", "description": "Organization details updated"},
                {"value": "zen:event-type:organization.deleted", "label": "Organization Deleted", "description": "Organization removed"},
                {"value": "zen:event-type:organization.name_changed", "label": "Name Changed", "description": "Organization name modified"},
                {"value": "zen:event-type:organization.tags_changed", "label": "Tags Changed", "description": "Organization tags updated"},
                {"value": "zen:event-type:organization.custom_field_changed", "label": "Custom Field Changed", "description": "Custom field value updated"},
                {"value": "zen:event-type:organization.external_id_changed", "label": "External ID Changed", "description": "External ID modified"}
            ]
        },
        
        "article": {
            "name": "Article Events",
            "description": "Knowledge base article events",
            "events": [
                {"value": "zen:event-type:article.published", "label": "Article Published", "description": "Article made public"},
                {"value": "zen:event-type:article.unpublished", "label": "Article Unpublished", "description": "Article hidden from public"},
                {"value": "zen:event-type:article.author_changed", "label": "Author Changed", "description": "Article author updated"},
                {"value": "zen:event-type:article.vote_changed", "label": "Vote Changed", "description": "Article voting updated"},
                {"value": "zen:event-type:article.comment_created", "label": "Comment Created", "description": "Comment added to article"},
                {"value": "zen:event-type:article.subscription_created", "label": "Subscription Created", "description": "User subscribed to article"},
                {"value": "zen:event-type:article.subscription_deleted", "label": "Subscription Deleted", "description": "User unsubscribed from article"},
                {"value": "zen:event-type:article.label_added", "label": "Label Added", "description": "Label added to article"}
            ]
        },
        
        "community": {
            "name": "Community Events",
            "description": "Community post and engagement events",
            "events": [
                {"value": "zen:event-type:community_post.published", "label": "Post Published", "description": "Community post published"},
                {"value": "zen:event-type:community_post.vote_changed", "label": "Vote Changed", "description": "Post voting updated"},
                {"value": "zen:event-type:community_post.comment_created", "label": "Comment Created", "description": "Comment added to post"},
                {"value": "zen:event-type:community_post.subscription_created", "label": "Subscription Created", "description": "User subscribed to post"},
                {"value": "zen:event-type:community_post.subscription_deleted", "label": "Subscription Deleted", "description": "User unsubscribed from post"}
            ]
        },
        
        "agent_availability": {
            "name": "Agent Availability Events",
            "description": "Agent status and capacity monitoring",
            "events": [
                {"value": "zen:event-type:agent_availability.agent_state_changed", "label": "Agent State Changed", "description": "Agent online/offline status changed"},
                {"value": "zen:event-type:agent_availability.unified_agent_state_changed", "label": "Unified Agent State Changed", "description": "Unified agent state modified"},
                {"value": "zen:event-type:agent_availability.work_item_created", "label": "Work Item Created", "description": "New work item assigned"},
                {"value": "zen:event-type:agent_availability.work_item_status_changed", "label": "Work Item Status Changed", "description": "Work item status updated"},
                {"value": "zen:event-type:agent_availability.unified_agent_state_capacity_changed", "label": "Capacity Changed", "description": "Agent capacity modified"}
            ]
        }
    }
    
    @classmethod
    def get_all_categories(cls) -> List[ZendeskEventCategory]:
        """Get all event categories with counts"""
        return [
            ZendeskEventCategory(
                key=key,
                name=data["name"],
                description=data["description"],
                count=len(data["events"])
            )
            for key, data in cls.EVENT_TYPES.items()
        ]
    
    @classmethod
    def get_events_by_category(cls, category: str) -> List[ZendeskEventType]:
        """Get all events in a specific category"""
        if category not in cls.EVENT_TYPES:
            raise ValueError(f"Invalid category: {category}")
        
        return [
            ZendeskEventType(**event, category=category)
            for event in cls.EVENT_TYPES[category]["events"]
        ]
    
    @classmethod
    def get_all_events(cls) -> List[ZendeskEventType]:
        """Get all events across all categories"""
        all_events = []
        for category_key in cls.EVENT_TYPES:
            all_events.extend(cls.get_events_by_category(category_key))
        return all_events
    
    @classmethod
    def search_events(cls, query: str) -> List[ZendeskEventType]:
        """Search events by label or description"""
        query_lower = query.lower()
        results = []
        for category_key in cls.EVENT_TYPES:
            for event in cls.EVENT_TYPES[category_key]["events"]:
                if (query_lower in event["label"].lower() or 
                    query_lower in event["description"].lower() or
                    query_lower in event["value"].lower()):
                    results.append(ZendeskEventType(**event, category=category_key))
        return results

# ============================================================================
# HubSpot Event Manager (Comprehensive List)
# ============================================================================

class HubSpotEventManager:
    """
    Complete HubSpot webhook event types for private apps
    Covers all CRM objects with comprehensive event support
    """
    
    EVENT_TYPES = {
        "contact": {
            "object_name": "Contacts",
            "scope_required": "crm.objects.contacts.read",
            "description": "Contact lifecycle and property events",
            "events": [
                {"value": "contact.creation", "label": "Contact Created", "description": "New contact created"},
                {"value": "contact.deletion", "label": "Contact Deleted", "description": "Contact permanently deleted"},
                {"value": "contact.propertyChange", "label": "Property Changed", "description": "Contact property updated"},
                {"value": "contact.merge", "label": "Contact Merged", "description": "Contacts merged together"},
                {"value": "contact.associationChange", "label": "Association Changed", "description": "Contact associations modified"},
                {"value": "contact.restore", "label": "Contact Restored", "description": "Deleted contact restored"},
                {"value": "contact.privacyDeletion", "label": "Privacy Deletion", "description": "GDPR deletion executed"}
            ]
        },
        "company": {
            "object_name": "Companies",
            "scope_required": "crm.objects.companies.read",
            "description": "Company object events",
            "events": [
                {"value": "company.creation", "label": "Company Created", "description": "New company created"},
                {"value": "company.deletion", "label": "Company Deleted", "description": "Company permanently deleted"},
                {"value": "company.propertyChange", "label": "Property Changed", "description": "Company property updated"},
                {"value": "company.merge", "label": "Company Merged", "description": "Companies merged together"},
                {"value": "company.associationChange", "label": "Association Changed", "description": "Company associations modified"},
                {"value": "company.restore", "label": "Company Restored", "description": "Deleted company restored"}
            ]
        },
        "deal": {
            "object_name": "Deals",
            "scope_required": "crm.objects.deals.read",
            "description": "Deal pipeline and stage events",
            "events": [
                {"value": "deal.creation", "label": "Deal Created", "description": "New deal created"},
                {"value": "deal.deletion", "label": "Deal Deleted", "description": "Deal permanently deleted"},
                {"value": "deal.propertyChange", "label": "Property Changed", "description": "Deal property updated (includes stage)"},
                {"value": "deal.merge", "label": "Deal Merged", "description": "Deals merged together"},
                {"value": "deal.associationChange", "label": "Association Changed", "description": "Deal associations modified"},
                {"value": "deal.restore", "label": "Deal Restored", "description": "Deleted deal restored"}
            ]
        },
        "ticket": {
            "object_name": "Tickets",
            "scope_required": "tickets",
            "description": "Support ticket events",
            "events": [
                {"value": "ticket.creation", "label": "Ticket Created", "description": "New ticket created"},
                {"value": "ticket.deletion", "label": "Ticket Deleted", "description": "Ticket permanently deleted"},
                {"value": "ticket.propertyChange", "label": "Property Changed", "description": "Ticket property updated"},
                {"value": "ticket.merge", "label": "Ticket Merged", "description": "Tickets merged together"},
                {"value": "ticket.associationChange", "label": "Association Changed", "description": "Ticket associations modified"},
                {"value": "ticket.restore", "label": "Ticket Restored", "description": "Deleted ticket restored"}
            ]
        },
        "product": {
            "object_name": "Products",
            "scope_required": "e-commerce",
            "description": "Product catalog events",
            "events": [
                {"value": "product.creation", "label": "Product Created", "description": "New product created"},
                {"value": "product.deletion", "label": "Product Deleted", "description": "Product permanently deleted"},
                {"value": "product.propertyChange", "label": "Property Changed", "description": "Product property updated"},
                {"value": "product.merge", "label": "Product Merged", "description": "Products merged together"},
                {"value": "product.restore", "label": "Product Restored", "description": "Deleted product restored"}
            ]
        },
        "line_item": {
            "object_name": "Line Items",
            "scope_required": "e-commerce",
            "description": "Deal line item events",
            "events": [
                {"value": "line_item.creation", "label": "Line Item Created", "description": "New line item created"},
                {"value": "line_item.deletion", "label": "Line Item Deleted", "description": "Line item permanently deleted"},
                {"value": "line_item.propertyChange", "label": "Property Changed", "description": "Line item property updated"},
                {"value": "line_item.merge", "label": "Line Item Merged", "description": "Line items merged together"},
                {"value": "line_item.restore", "label": "Line Item Restored", "description": "Deleted line item restored"}
            ]
        },
        "conversation": {
            "object_name": "Conversations (Beta)",
            "scope_required": "conversations.read",
            "description": "Conversation and messaging events",
            "events": [
                {"value": "conversation.creation", "label": "Conversation Created", "description": "New conversation started"},
                {"value": "conversation.deletion", "label": "Conversation Deleted", "description": "Conversation deleted"},
                {"value": "conversation.newMessage", "label": "New Message", "description": "New message in conversation"},
                {"value": "conversation.propertyChange", "label": "Property Changed", "description": "Limited properties: assignedTo, status, isArchived"},
                {"value": "conversation.privacyDeletion", "label": "Privacy Deletion", "description": "GDPR deletion executed"}
            ]
        }
    }
    
    EXCLUDED_PROPERTIES = [
        "hs_lastmodifieddate",
        "num_unique_conversion_events",
        "hs_all_owner_ids",
        "hs_all_team_ids",
        "hs_all_accessible_team_ids"
    ]
    
    @classmethod
    def get_all_object_types(cls) -> List[Dict[str, Any]]:
        """Get all HubSpot object types with event counts"""
        return [
            {
                "key": key,
                "name": data["object_name"],
                "scope": data["scope_required"],
                "description": data["description"],
                "event_count": len(data["events"]),
                "is_beta": "(Beta)" in data["object_name"]
            }
            for key, data in cls.EVENT_TYPES.items()
        ]
    
    @classmethod
    def get_events_by_object(cls, object_type: str) -> List[HubSpotEventType]:
        """Get all events for a specific object type"""
        if object_type not in cls.EVENT_TYPES:
            raise ValueError(f"Invalid object type: {object_type}")
        
        data = cls.EVENT_TYPES[object_type]
        return [
            HubSpotEventType(
                object_type=object_type,
                event_types=[event["value"]],
                scope_required=data["scope_required"]
            )
            for event in data["events"]
        ]
    
    @classmethod
    def get_all_events(cls) -> List[Dict[str, Any]]:
        """Get all events across all object types"""
        all_events = []
        for obj_type, data in cls.EVENT_TYPES.items():
            for event in data["events"]:
                all_events.append({
                    "object_type": obj_type,
                    "event_value": event["value"],
                    "label": event["label"],
                    "description": event["description"],
                    "scope_required": data["scope_required"]
                })
        return all_events

# ============================================================================
# Security: Signature Verification
# ============================================================================

class SignatureVerifier:
    """Enterprise-grade signature verification with timing attack protection"""
    
    @staticmethod
    def verify_zendesk_signature(
        signature: str,
        timestamp: str,
        body: str,
        signing_secret: str
    ) -> bool:
        """
        Verify Zendesk webhook signature using HMAC SHA-256
        
        Args:
            signature: X-Zendesk-Webhook-Signature header
            timestamp: X-Zendesk-Webhook-Signature-Timestamp header
            body: Raw request body
            signing_secret: Webhook signing secret from Zendesk
        
        Returns:
            bool: True if signature is valid
        """
        try:
            # Construct message: timestamp + body
            message = timestamp + body
            
            # Create HMAC SHA-256 hash
            computed_hmac = hmac.new(
                signing_secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            )
            
            # Base64 encode
            computed_signature = base64.b64encode(computed_hmac.digest()).decode('utf-8')
            
            # Constant-time comparison to prevent timing attacks
            return hmac.compare_digest(computed_signature, signature)
            
        except Exception as e:
            logger.error(f"Zendesk signature verification failed: {e}")
            return False
    
    @staticmethod
    def verify_hubspot_signature_v3(
        signature: str,
        timestamp: str,
        method: str,
        uri: str,
        body: str,
        client_secret: str
    ) -> bool:
        """
        Verify HubSpot webhook signature v3 using HMAC SHA-256
        
        Args:
            signature: X-HubSpot-Signature-v3 header
            timestamp: X-HubSpot-Request-Timestamp header
            method: HTTP method (POST)
            uri: Full request URI including protocol
            body: Raw request body
            client_secret: HubSpot app client secret
        
        Returns:
            bool: True if signature is valid and timestamp is fresh
        """
        try:
            # 1. Validate timestamp (must be within 5 minutes)
            current_time = datetime.utcnow().timestamp() * 1000  # Convert to milliseconds
            request_time = int(timestamp)
            
            if current_time - request_time > TIMESTAMP_MAX_AGE:
                logger.warning(f"HubSpot webhook timestamp too old: {current_time - request_time}ms")
                return False
            
            # 2. URL decode specific characters
            decoded_uri = SignatureVerifier._url_decode_hubspot(uri)
            
            # 3. Concatenate components
            source_string = method + decoded_uri + body + timestamp
            
            # 4. Create HMAC SHA-256 hash
            computed_hmac = hmac.new(
                client_secret.encode('utf-8'),
                source_string.encode('utf-8'),
                hashlib.sha256
            )
            
            # 5. Base64 encode
            computed_signature = base64.b64encode(computed_hmac.digest()).decode('utf-8')
            
            # Constant-time comparison
            return hmac.compare_digest(computed_signature, signature)
            
        except Exception as e:
            logger.error(f"HubSpot signature verification failed: {e}")
            return False
    
    @staticmethod
    def _url_decode_hubspot(uri: str) -> str:
        """
        URL decode specific characters for HubSpot v3 signature verification
        """
        decode_map = {
            '%3A': ':', '%2F': '/', '%3F': '?', '%40': '@',
            '%21': '!', '%24': '$', '%27': "'", '%28': '(',
            '%29': ')', '%2A': '*', '%2C': ',', '%3B': ';'
        }
        
        decoded = uri
        for encoded, decoded_char in decode_map.items():
            decoded = decoded.replace(encoded, decoded_char)
        
        return decoded

# ============================================================================
# Idempotency Manager
# ============================================================================

class IdempotencyManager:
    """Redis-based idempotency to prevent duplicate event processing"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.ttl = 900  # 15 minutes
    
    async def is_processed(self, event_id: str, platform: str) -> bool:
        """Check if event has been processed"""
        key = f"idempotency:{platform}:{event_id}"
        exists = await self.redis.exists(key)
        return bool(exists)
    
    async def mark_processed(self, event_id: str, platform: str) -> None:
        """Mark event as processed"""
        key = f"idempotency:{platform}:{event_id}"
        await self.redis.setex(key, self.ttl, "1")
        logger.info(f"Event marked as processed: {platform}:{event_id}")
    
    async def get_attempt_count(self, event_id: str, platform: str) -> int:
        """Get retry attempt count for monitoring"""
        key = f"attempt:{platform}:{event_id}"
        count = await self.redis.get(key)
        return int(count) if count else 0
    
    async def increment_attempt(self, event_id: str, platform: str) -> int:
        """Increment and return attempt count"""
        key = f"attempt:{platform}:{event_id}"
        count = await self.redis.incr(key)
        await self.redis.expire(key, self.ttl)
        return count

# ============================================================================
# Circuit Breaker
# ============================================================================

class CircuitBreaker:
    """
    Circuit breaker to prevent overwhelming broken endpoints
    Tracks error rates and automatically pauses processing
    """
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.window = CIRCUIT_BREAKER_TIME_WINDOW
        self.error_threshold = CIRCUIT_BREAKER_ERROR_THRESHOLD
        self.min_requests = CIRCUIT_BREAKER_MIN_REQUESTS
    
    async def record_request(self, platform: str, success: bool) -> None:
        """Record request outcome"""
        timestamp = int(datetime.utcnow().timestamp())
        key = f"circuit:{platform}:{timestamp}"
        value = "success" if success else "error"
        
        await self.redis.setex(key, self.window, value)
    
    async def is_open(self, platform: str) -> bool:
        """Check if circuit breaker is open (blocking requests)"""
        now = int(datetime.utcnow().timestamp())
        keys_pattern = f"circuit:{platform}:*"
        
        # Get all keys in time window
        keys = []
        async for key in self.redis.scan_iter(match=keys_pattern):
            timestamp = int(key.decode().split(':')[-1])
            if now - timestamp <= self.window:
                keys.append(key)
        
        if len(keys) < self.min_requests:
            return False
        
        # Count errors
        error_count = 0
        for key in keys:
            value = await self.redis.get(key)
            if value and value.decode() == "error":
                error_count += 1
        
        error_rate = error_count / len(keys)
        
        if error_rate >= self.error_threshold or error_count >= 1000:
            logger.warning(f"Circuit breaker OPEN for {platform}: {error_rate:.2%} error rate")
            return True
        
        return False

# ============================================================================
# Async Event Processor
# ============================================================================

class EventProcessor:
    """Async background processor for webhook events"""
    
    @staticmethod
    async def process_zendesk_event(event: Dict[str, Any]) -> None:
        """Process Zendesk event asynchronously"""
        try:
            event_type = event.get('type', 'unknown')
            event_id = event.get('id', 'unknown')
            
            logger.info(f"Processing Zendesk event: {event_type} (ID: {event_id})")
            
            # Add your business logic here
            # Examples:
            # - Create records in your database
            # - Trigger workflows
            # - Send notifications
            # - Update external systems
            
            await asyncio.sleep(0.1)  # Simulate processing
            
            logger.info(f"Successfully processed Zendesk event: {event_id}")
            
        except Exception as e:
            logger.error(f"Error processing Zendesk event: {e}", exc_info=True)
            raise
    
    @staticmethod
    async def process_hubspot_event(event: Dict[str, Any]) -> None:
        """Process HubSpot event asynchronously"""
        try:
            event_id = event.get('eventId', 'unknown')
            subscription_type = event.get('subscriptionType', 'unknown')
            attempt_number = event.get('attemptNumber', 0)
            
            logger.info(f"Processing HubSpot event: {subscription_type} (ID: {event_id}, Attempt: {attempt_number})")
            
            # Add your business logic here
            # Handle different event types:
            # - contact.creation, contact.propertyChange, etc.
            # - deal.creation, deal.propertyChange, etc.
            # - company, ticket, product events
            
            await asyncio.sleep(0.1)  # Simulate processing
            
            logger.info(f"Successfully processed HubSpot event: {event_id}")
            
        except Exception as e:
            logger.error(f"Error processing HubSpot event: {e}", exc_info=True)
            raise

# ============================================================================
# API Helper Functions
# ============================================================================

def get_zendesk_headers(subdomain: str, email: str, api_key: str) -> Dict[str, str]:
    """Generate Zendesk API headers with Basic Auth"""
    auth_string = f"{email}/token:{api_key}"
    auth_bytes = base64.b64encode(auth_string.encode()).decode()
    
    return {
        "Authorization": f"Basic {auth_bytes}",
        "Content-Type": "application/json"
    }

# ============================================================================
# Dependency Injection
# ============================================================================

async def get_idempotency_manager() -> IdempotencyManager:
    """Dependency injection for idempotency manager"""
    return IdempotencyManager(redis_client)

async def get_circuit_breaker() -> CircuitBreaker:
    """Dependency injection for circuit breaker"""
    return CircuitBreaker(redis_client)

# ============================================================================
# API Endpoints: Zendesk
# ============================================================================

@app.post("/zendesk/test-connection")
async def zendesk_test_connection(payload: ZendeskTestConnection):
    """
    Test Zendesk API connection with provided credentials
    
    Returns user details if authentication succeeds
    """
    url = f"https://{payload.subdomain}.zendesk.com/api/v2/users/me.json"
    headers = get_zendesk_headers(payload.subdomain, payload.email, payload.api_key)
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            user = response.json().get("user", {})
            return {
                "status": ConnectionStatus.SUCCESS,
                "user_name": user.get("name", "Unknown"),
                "user_email": user.get("email", "N/A"),
                "role": user.get("role", "N/A"),
                "account_id": user.get("organization_id"),
                "message": "Connection successful!"
            }
        else:
            raise HTTPException(
                status_code=401,
                detail=f"Authentication failed: {response.text}"
            )
            
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Connection timeout")
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        raise HTTPException(status_code=500, detail=f"Connection failed: {str(e)}")

@app.get("/zendesk/event-categories")
async def get_zendesk_categories():
    """
    Get all Zendesk event categories with event counts
    
    Returns comprehensive list of all 6 major event domains
    """
    return {
        "total_categories": len(ZendeskEventManager.EVENT_TYPES),
        "categories": ZendeskEventManager.get_all_categories()
    }

@app.get("/zendesk/events/{category}")
async def get_zendesk_events_by_category(category: str):
    """
    Get all events in a specific Zendesk category
    
    Supports: ticket, user, organization, article, community, agent_availability
    """
    try:
        events = ZendeskEventManager.get_events_by_category(category)
        return {
            "category": category,
            "event_count": len(events),
            "events": events
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/zendesk/events")
async def get_all_zendesk_events():
    """
    Get all Zendesk webhook events across all categories
    
    Returns 90+ comprehensive event types
    """
    events = ZendeskEventManager.get_all_events()
    
    # Group by category for better organization
    grouped = {}
    for event in events:
        if event.category not in grouped:
            grouped[event.category] = []
        grouped[event.category].append(event)
    
    return {
        "total_events": len(events),
        "categories": grouped,
        "flat_list": events
    }

@app.get("/zendesk/events/search")
async def search_zendesk_events(q: str):
    """
    Search Zendesk events by keyword in label, description, or value
    
    Example: ?q=ticket or ?q=created or ?q=comment
    """
    results = ZendeskEventManager.search_events(q)
    return {
        "query": q,
        "result_count": len(results),
        "results": results
    }

@app.post("/zendesk/webhooks")
async def create_zendesk_webhook(payload: ZendeskCreateWebhook):
    """
    Create a new Zendesk webhook programmatically
    
    Supports full authentication configuration and custom headers
    """
    headers = get_zendesk_headers(payload.subdomain, payload.email, payload.api_key)
    url = f"https://{payload.subdomain}.zendesk.com/api/v2/webhooks"
    
    webhook_payload = {
        "webhook": {
            "name": payload.name,
            "status": "active",
            "endpoint": str(payload.endpoint),
            "http_method": "POST",
            "request_format": "json",
            "subscriptions": payload.subscriptions
        }
    }
    
    # Add authentication if provided
    if payload.authentication:
        auth_data = payload.authentication.data
        if payload.authentication.type == ZendeskAuthType.API_KEY:
            webhook_payload["webhook"]["authentication"] = {
                "type": "api_key",
                "data": {
                    "name": auth_data["name"],
                    "value": auth_data["value"]
                },
                "add_position": "header"
            }
        elif payload.authentication.type == ZendeskAuthType.BASIC_AUTH:
            webhook_payload["webhook"]["authentication"] = {
                "type": "basic_auth",
                "data": {
                    "username": auth_data["username"],
                    "password": auth_data["password"]
                }
            }
        elif payload.authentication.type == ZendeskAuthType.BEARER_TOKEN:
            webhook_payload["webhook"]["authentication"] = {
                "type": "bearer_token",
                "data": {
                    "token": auth_data["token"]
                },
                "add_position": "header"
            }
    
    # Add custom headers if provided
    if payload.custom_headers:
        webhook_payload["webhook"]["custom_headers"] = payload.custom_headers
    
    try:
        response = requests.post(url, headers=headers, json=webhook_payload, timeout=15)
        
        if response.status_code == 201:
            webhook = response.json().get("webhook", {})
            return {
                "success": True,
                "webhook_id": webhook.get("id"),
                "name": webhook.get("name"),
                "endpoint": webhook.get("endpoint"),
                "status": webhook.get("status"),
                "subscriptions": webhook.get("subscriptions", []),
                "created_at": webhook.get("created_at"),
                "signing_secret_info": "Retrieve via GET /api/v2/webhooks/{webhook_id}/signing_secret"
            }
        else:
            error_data = response.json()
            raise HTTPException(
                status_code=response.status_code,
                detail=error_data.get("description", response.text)
            )
            
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Request timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create webhook: {str(e)}")

# ============================================================================
# API Endpoints: HubSpot
# ============================================================================

@app.post("/hubspot/test-connection")
async def hubspot_test_connection(payload: HubSpotTestConnection):
    """
    Test HubSpot API connection with access token
    Works with both private app tokens and OAuth tokens
    """
    url = "https://api.hubapi.com/crm/v3/objects/contacts"
    headers = {
        "Authorization": f"Bearer {payload.access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Try to fetch first contact to test connection
        response = requests.get(f"{url}?limit=1", headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "status": ConnectionStatus.SUCCESS,
                "message": "HubSpot connection successful!",
                "api_status": "active",
                "contact_count": data.get("total", 0)
            }
        elif response.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail="Authentication failed. Check your access token."
            )
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"HubSpot API error: {response.text}"
            )
            
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Connection timeout")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"HubSpot connection test failed: {e}")
        raise HTTPException(status_code=500, detail=f"Connection failed: {str(e)}")
@app.post("/hubspot/webhooks", response_model=HubSpotWebhookResponse)
async def create_hubspot_webhook(payload: HubSpotCreateWebhook):
    """
    Create HubSpot webhook subscriptions for Public OAuth Apps.
    """
    
    # Step 1: Set the target URL
    settings_url = f"https://api.hubapi.com/webhooks/v3/{payload.app_id}/settings?hapikey={payload.developer_api_key}"
    
    try:
        settings_response = requests.put(
            settings_url,
            headers={"Content-Type": "application/json"},
            json={"targetUrl": payload.endpoint_url},
            timeout=10
        )
        
        if settings_response.status_code not in [200, 204]:
            logger.error(f"Failed to set target URL: {settings_response.text}")
            raise HTTPException(
                status_code=settings_response.status_code,
                detail=f"Failed to set webhook target URL: {settings_response.json().get('message', settings_response.text)}"
            )
        
        logger.info(f"✅ Webhook target URL set successfully: {payload.endpoint_url}")
        
        # ✅ GET settings to retrieve clientSecret
        logger.info("🔍 Fetching app-level settings to get clientSecret...")
        get_settings_response = requests.get(
            settings_url,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        app_level_secret = None
        if get_settings_response.status_code == 200:
            settings_data = get_settings_response.json()
            logger.info(f"🔍 Settings Response: {json.dumps(settings_data, indent=2)}")
            
            app_level_secret = settings_data.get("clientSecret")
            if app_level_secret:
                logger.info(f"✅ Found app-level clientSecret: {app_level_secret[:10]}...")
            else:
                logger.warning(f"⚠️ No clientSecret in settings. Available keys: {list(settings_data.keys())}")
        else:
            logger.error(f"❌ Failed to get settings: {get_settings_response.status_code} - {get_settings_response.text}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in settings endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to configure webhook: {str(e)}")
    
    # Step 2: Create subscriptions
    base_url = f"https://api.hubapi.com/webhooks/v3/{payload.app_id}/subscriptions?hapikey={payload.developer_api_key}"
    
    created_subscriptions = []
    signing_secrets = {}
    errors = []

    for subscription in payload.subscriptions:
        subscription_payload = {
            "eventType": subscription.subscription_type,
            "active": True
        }
        
        if subscription.property_name:
            subscription_payload["propertyName"] = subscription.property_name

        try:
            response = requests.post(
                base_url,
                headers={"Content-Type": "application/json"},
                json=subscription_payload,
                timeout=15
            )

            if response.status_code == 201:
                sub_data = response.json()
                
                # ✅ Debug: Print full subscription response
                logger.info(f"🔍 Subscription Response: {json.dumps(sub_data, indent=2)}")
                
                subscription_id = sub_data.get("id")
                client_secret = sub_data.get("clientSecret")
                
                created_subscriptions.append({
                    "id": subscription_id,
                    "type": subscription.subscription_type,
                    "property": subscription.property_name,
                    "status": "created"
                })
                
                # Check if clientSecret is in subscription response
                if client_secret:
                    signing_secrets[subscription_id] = client_secret
                    logger.info(f"✅ Got clientSecret from subscription: {client_secret[:10]}...")
                else:
                    logger.warning(f"⚠️ No clientSecret in subscription response")
                    logger.warning(f"⚠️ Available keys in subscription: {list(sub_data.keys())}")
                
                logger.info(f"✅ Created subscription: {subscription.subscription_type}")
            else:
                error_data = response.json()
                error_msg = error_data.get("message", response.text)
                errors.append({
                    "subscription": subscription.subscription_type,
                    "error": error_msg,
                    "status_code": response.status_code
                })
                logger.error(f"❌ Failed to create subscription {subscription.subscription_type}: {error_msg}")

        except Exception as e:
            errors.append({
                "subscription": subscription.subscription_type,
                "error": str(e)
            })
            logger.error(f"Exception creating subscription {subscription.subscription_type}: {e}")

    if not created_subscriptions and errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Failed to create any subscriptions",
                "errors": errors
            }
        )

    # ✅ Use app-level secret if individual subscriptions don't have it
    if app_level_secret and not signing_secrets:
        signing_secrets["app_level"] = app_level_secret
        logger.info("✅ Using app-level clientSecret for all subscriptions")

    return HubSpotWebhookResponse(
        success=len(created_subscriptions) > 0,
        subscription_ids=[sub["id"] for sub in created_subscriptions],
        signing_secrets=signing_secrets,
        webhook_url=payload.endpoint_url,
        total_subscriptions=len(created_subscriptions),
        message=f"✅ Created {len(created_subscriptions)} subscriptions" + 
                (f" (⚠️ {len(errors)} failed)" if errors else "")
    )

@app.get("/hubspot/event-types")
async def get_hubspot_event_types():
    """
    Get all HubSpot object types and their available events
    
    Note: HubSpot private apps require UI configuration.
    This endpoint documents available event types.
    """
    return {
        "note": "HubSpot private apps require webhook configuration via UI",
        "documentation_url": "Settings > Integrations > Private Apps > Webhooks tab",
        "object_types": HubSpotEventManager.get_all_object_types(),
        "total_objects": len(HubSpotEventManager.EVENT_TYPES)
    }

@app.get("/hubspot/events/{object_type}")
async def get_hubspot_events_by_object(object_type: str):
    """
    Get all events for a specific HubSpot object type
    
    Supports: contact, company, deal, ticket, product, line_item, conversation
    """
    try:
        events = HubSpotEventManager.get_events_by_object(object_type)
        data = HubSpotEventManager.EVENT_TYPES[object_type]
        
        return {
            "object_type": object_type,
            "object_name": data["object_name"],
            "scope_required": data["scope_required"],
            "description": data["description"],
            "event_count": len(data["events"]),
            "events": data["events"]
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/hubspot/events")
async def get_all_hubspot_events():
    """
    Get all HubSpot webhook events across all object types
    
    Returns comprehensive list with required scopes
    """
    all_events = HubSpotEventManager.get_all_events()
    
    return {
        "total_events": len(all_events),
        "note": "Configure these via HubSpot UI: Settings > Integrations > Private Apps > Webhooks",
        "events": all_events,
        "excluded_properties": HubSpotEventManager.EXCLUDED_PROPERTIES
    }

@app.post("/zendesk/get-signing-secret")
async def get_zendesk_signing_secret(
    subdomain: str,
    email: EmailStr,
    api_key: str,
    webhook_id: str
):
    """
    Get Zendesk webhook signing secret
    
    This secret is required for signature verification
    """
    url = f"https://{subdomain}.zendesk.com/api/v2/webhooks/{webhook_id}/signing_secret"
    headers = get_zendesk_headers(subdomain, email, api_key)
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            secret = data.get("signing_secret", {}).get("secret", "")
            
            return {
                "success": True,
                "webhook_id": webhook_id,
                "signing_secret": secret,
                "message": "⚠️ IMPORTANT: Copy this secret and update your code!",
                "instructions": [
                    "1. Copy the signing_secret value",
                    "2. Open your main.py file",
                    "3. Find line ~1029: signing_secret = 'YOUR_ZENDESK_SIGNING_SECRET'",
                    f"4. Replace with: signing_secret = '{secret}'",
                    "5. Restart your FastAPI server"
                ]
            }
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to get signing secret: {response.text}"
            )
            
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Request timeout")
    except Exception as e:
        logger.error(f"Failed to get signing secret: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ============================================================================
# Unified Webhook Receiver
# ============================================================================


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
)
async def universal_webhook_receiver(
    request: Request,
    full_path: str,
    x_zendesk_webhook_signature: str | None = Header(default=None),
    x_zendesk_webhook_signature_timestamp: str | None = Header(default=None),
    x_hubspot_signature_v3: str | None = Header(default=None, alias="X-HubSpot-Signature-v3"),
    x_hubspot_request_timestamp: str | None = Header(default=None, alias="X-HubSpot-Request-Timestamp"),
    authorization: str | None = Header(default=None)
):
    """
    🌍 Universal Webhook Receiver
    - Accepts any webhook (HubSpot, Zendesk, Stripe, GitHub, etc.)
    - Logs payloads
    - Verifies signatures
    """

    raw_body = await request.body()
    ip = request.client.host
    method = request.method
    now = datetime.now().strftime("%I:%M:%S %p")

    print("\n" + "═" * 80)
    print(f"📩 WEBHOOK RECEIVED ({method}) at /{full_path}")
    print(f"🕓 Time: {now}")
    print(f"🌐 From: {ip}")
    print("─" * 80)

    # Try parsing JSON
    try:
        data = json.loads(raw_body)
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        print(pretty)
    except Exception:
        pretty = raw_body.decode("utf-8", errors="replace") if raw_body else "Empty body"
        data = {}

    print("─" * 80)

    # Detect and verify source
    source = "unknown"
    signature_status = "not_verified"
    #Zendesk verification
    if x_zendesk_webhook_signature and x_zendesk_webhook_signature_timestamp:
        source = "zendesk"
        try:
            secret = "VfqIyAffmA-lcH8bkn3iBlUAQZcRgXeoU6Z-8lgWfpI="
            base_string = x_zendesk_webhook_signature_timestamp + raw_body.decode()
            digest = hmac.new(secret.encode(), base_string.encode(), hashlib.sha256).digest()
            computed_signature = base64.b64encode(digest).decode()

            if hmac.compare_digest(computed_signature, x_zendesk_webhook_signature):
                signature_status = "verified"
                print("✅ Zendesk signature verified!")
            else:
                signature_status = "failed"
                print("Zendesk signature mismatch!")
        except Exception as e:
            signature_status = "error"
            print(f"⚠️ Zendesk verification error: {e}")

    # ✅ HubSpot signature verification (v3 method)
       
    elif x_hubspot_signature_v3 and x_hubspot_request_timestamp:
        source = "hubspot"
        try:
            client_secret = "77270ecb-6643-44af-9dd3-e439a3c97df5"
            
            print("\n🔍 HUBSPOT V3 SIGNATURE VERIFICATION:")
            print(f"   Timestamp: {x_hubspot_request_timestamp}")
            print(f"   Received v3 sig: {x_hubspot_signature_v3}")
            
            # 1. Validate timestamp (reject if older than 5 minutes)
            try:
                timestamp_ms = float(x_hubspot_request_timestamp)
                request_time = datetime.fromtimestamp(timestamp_ms / 1000)
                current_time = datetime.now()
                time_diff = (current_time - request_time).total_seconds()
                
                if time_diff > 300:  # 5 minutes
                    signature_status = "expired"
                    print(f"   ⏰ Timestamp too old: {time_diff:.1f}s")
                else:
                    print(f"   ✅ Timestamp valid: {time_diff:.1f}s ago")
                    
                    # 2. Get request details
                    method = request.method  # POST
                    
                    # Construct full URI
                    forwarded_proto = request.headers.get("x-forwarded-proto", "https")
                    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
                    path = request.url.path
                    query = f"?{request.url.query}" if request.url.query else ""
                    full_uri = f"{forwarded_proto}://{forwarded_host}{path}{query}"
                    
                    print(f"   Method: {method}")
                    print(f"   URI: {full_uri}")
                    
                    # 3. Get raw body as string
                    body_str = raw_body.decode('utf-8')
                    
                    # 4. Create source string: METHOD + URI + BODY + TIMESTAMP
                    # Note: No spaces or delimiters between components
                    source_string = method + full_uri + body_str + x_hubspot_request_timestamp
                    
                    print(f"   Source string preview: {source_string[:150]}...")
                    
                    # 5. Generate HMAC-SHA256 signature
                    hashed = hmac.new(
                        client_secret.encode('utf-8'),
                        msg=source_string.encode('utf-8'),
                        digestmod=hashlib.sha256
                    ).digest()
                    
                    # 6. Base64 encode the hash
                    computed_signature = base64.b64encode(hashed).decode('utf-8')
                    
                    print(f"\n   Computed: {computed_signature}")
                    print(f"   Received: {x_hubspot_signature_v3}")
                    
                    # 7. Compare signatures using constant-time comparison
                    if hmac.compare_digest(computed_signature, x_hubspot_signature_v3):
                        signature_status = "verified"
                        print(f"   ✅ V3 SIGNATURE VERIFIED!")
                    else:
                        signature_status = "failed"
                        print(f"  V3 SIGNATURE MISMATCH!")
                        
            except (ValueError, OverflowError) as e:
                signature_status = "invalid_timestamp"
                print(f"  Invalid timestamp format: {e}")
                
        except Exception as e:
            signature_status = "error"
            print(f"⚠️ V3 verification error: {e}")
            import traceback
            traceback.print_exc()
            
    # Debug: Show all headers (helpful for troubleshooting)
    print("\n📋 Headers received:")
    for header, value in request.headers.items():
        if 'signature' in header.lower() or 'timestamp' in header.lower():
            print(f"   {header}: {value}")
    
    print("═" * 80 + "\n")

    return JSONResponse({
        "status": "RECEIVED",
        "source": source,
        "signature_status": signature_status,
        "path": full_path,
        "from": ip,
        "time": now,
        "message": "Webhook captured successfully!"
    })
@app.get("/")
async def root():
    return {"status": "Universal Webhook Server is LIVE"}
@app.post("/webhook/hubspot")
async def receive_hubspot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hubspot_signature_v3: str = Header(..., alias="X-HubSpot-Signature-v3"),
    x_hubspot_request_timestamp: str = Header(..., alias="X-HubSpot-Request-Timestamp"),
    idempotency: IdempotencyManager = Depends(get_idempotency_manager),
    circuit_breaker: CircuitBreaker = Depends(get_circuit_breaker)
):
    """
    Secure HubSpot webhook receiver with v3 signature verification,
    timestamp validation, idempotency, and async batch processing
    """
    start_time = datetime.utcnow()
    
    # Check circuit breaker
    if await circuit_breaker.is_open(PlatformType.HUBSPOT):
        logger.warning("HubSpot circuit breaker is OPEN - rejecting request")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    
    try:
        # Get raw body and URI
        raw_body = await request.body()
        body_str = raw_body.decode('utf-8')
        
        # Construct full URI
        scheme = request.url.scheme
        hostname = request.headers.get("host", "localhost")
        path = request.url.path
        query = f"?{request.url.query}" if request.url.query else ""
        full_uri = f"{scheme}://{hostname}{path}{query}"
        
        # TODO: Replace with your HubSpot app client secret
        client_secret = "YOUR_HUBSPOT_CLIENT_SECRET"
        
        # Verify signature
        is_valid = SignatureVerifier.verify_hubspot_signature_v3(
            signature=x_hubspot_signature_v3,
            timestamp=x_hubspot_request_timestamp,
            method=request.method,
            uri=full_uri,
            body=body_str,
            client_secret=client_secret
        )
        
        if not is_valid:
            logger.warning("HubSpot signature verification failed")
            await circuit_breaker.record_request(PlatformType.HUBSPOT, success=False)
            raise HTTPException(status_code=401, detail="Invalid signature or expired timestamp")
        
        # Parse events (HubSpot sends array of events)
        events = json.loads(body_str)
        
        if not isinstance(events, list):
            events = [events]
        
        processed_count = 0
        duplicate_count = 0
        
        # Process each event
        for event in events:
            event_id = str(event.get('eventId', 'unknown'))
            subscription_type = event.get('subscriptionType', 'unknown')
            attempt_number = event.get('attemptNumber', 0)
            
            # Track retry attempts
            attempt_count = await idempotency.get_attempt_count(event_id, PlatformType.HUBSPOT)
            if attempt_count != attempt_number:
                logger.warning(f"Attempt number mismatch: stored={attempt_count}, received={attempt_number}")
            
            # Check idempotency
            if await idempotency.is_processed(event_id, PlatformType.HUBSPOT):
                duplicate_count += 1
                continue
            
            # Mark as processed
            await idempotency.mark_processed(event_id, PlatformType.HUBSPOT)
            await idempotency.increment_attempt(event_id, PlatformType.HUBSPOT)
            
            # Add to background processing
            background_tasks.add_task(EventProcessor.process_hubspot_event, event)
            processed_count += 1
        
        # Record success
        await circuit_breaker.record_request(PlatformType.HUBSPOT, success=True)
        
        processing_time = (datetime.utcnow() - start_time).total_seconds()
        
        logger.info(f"HubSpot webhook batch received: {processed_count} new, {duplicate_count} duplicates - {processing_time:.3f}s")
        
        return JSONResponse({
            "status": "success",
            "message": "Events received and queued for processing",
            "total_events": len(events),
            "processed_events": processed_count,
            "duplicate_events": duplicate_count,
            "processing_time_ms": int(processing_time * 1000)
        })
        
    except HTTPException:
        raise
    except json.JSONDecodeError:
        await circuit_breaker.record_request(PlatformType.HUBSPOT, success=False)
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        await circuit_breaker.record_request(PlatformType.HUBSPOT, success=False)
        logger.error(f"HubSpot webhook processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

# ============================================================================
# Health & Monitoring
# ============================================================================

@app.get("/")
async def root():
    """API health check"""
    return {
        "service": "FlowGenX AI - Unified Webhook System",
        "version": "2.0.0",
        "status": "operational",
        "platforms": [PlatformType.ZENDESK, PlatformType.HUBSPOT],
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    """Detailed health check with Redis connectivity"""
    redis_status = "connected"
    try:
        await redis_client.ping()
    except Exception as e:
        redis_status = f"error: {str(e)}"
    
    return {
        "status": "healthy",
        "redis": redis_status,
        "timestamp": datetime.utcnow().isoformat(),
        "uptime": "N/A"  # Implement uptime tracking if needed
    }

@app.get("/docs-info")
async def documentation_info():
    """
    Get comprehensive documentation about available endpoints,
    event types, and configuration guides
    """
    return {
        "api_documentation": "/docs",
        "zendesk": {
            "test_connection": "POST /zendesk/test-connection",
            "list_categories": "GET /zendesk/event-categories",
            "list_all_events": "GET /zendesk/events",
            "events_by_category": "GET /zendesk/events/{category}",
            "search_events": "GET /zendesk/events/search?q=keyword",
            "create_webhook": "POST /zendesk/webhooks",
            "webhook_receiver": "POST /webhook/zendesk",
            "total_events": "90+",
            "categories": ["ticket", "user", "organization", "article", "community", "agent_availability"]
        },
        "hubspot": {
            "test_connection": "POST /hubspot/test-connection",
            "create_webhook": "POST /hubspot/webhooks (Public OAuth app only)",
            "list_object_types": "GET /hubspot/event-types",
            "events_by_object": "GET /hubspot/events/{object_type}",
            "list_all_events": "GET /hubspot/events",
            "configuration_guide": "GET /hubspot/configuration-guide",
            "webhook_receiver": "POST /webhook/hubspot",
            "note": "✅ Public apps support API automation | ⚠️ Private apps require UI configuration",
            "objects": ["contact", "company", "deal", "ticket", "product", "line_item", "conversation"]
        },
        "security": {
            "signature_verification": "HMAC SHA-256",
            "zendesk_method": "Single unified method",
            "hubspot_method": "v3 with timestamp validation",
            "idempotency": "Redis-based with 15-minute TTL",
            "circuit_breaker": "70% error threshold with 5-minute window",
            "replay_protection": "5-minute timestamp window"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)