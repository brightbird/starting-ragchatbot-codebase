from openai import OpenAI
from typing import List, Optional, Dict, Any

class AIGenerator:
    """Handles interactions with ModelScope's Qwen API for generating responses"""
    
    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to comprehensive search tools for course information.

Search Tool Usage:
- Use the search_course_content tool for questions about specific course content or detailed educational materials
- Use the get_course_outline tool for questions about course structure, titles, links, and lesson lists
- **You may use up to two tools in sequence when needed to fully answer a question**
- Synthesize search results into accurate, fact-based responses
- If search yields no results, state this clearly without offering alternatives

Response Protocol:
- **General knowledge questions**: Answer using existing knowledge without searching
- **Course-specific questions**: Search first, then answer
- **No meta-commentary**:
 - Provide direct answers only — no reasoning process, search explanations, or question-type analysis
 - Do not mention "based on the search results"


All responses must be:
1. **Brief, Concise and focused** - Get to the point quickly
2. **Educational** - Maintain instructional value
3. **Clear** - Use accessible language
4. **Example-supported** - Include relevant examples when they aid understanding
Provide only the direct answer to what was asked.
"""
    
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(
            base_url='https://api-inference.modelscope.cn/v1',
            api_key=api_key,
        )
        self.model = model
        
        # Pre-build base API parameters
        self.base_params = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 800
        }
    
    def generate_response(self, query: str,
                         conversation_history: Optional[str] = None,
                         tools: Optional[List] = None,
                         tool_manager=None) -> str:
        """
        Generate AI response with optional tool usage and conversation context.
        Supports sequential tool calling with up to 2 rounds.
        
        Args:
            query: The user's question or request
            conversation_history: Previous messages for context
            tools: Available tools the AI can use
            tool_manager: Manager to execute tools
            
        Returns:
            Generated response as string
        """
        
        # Build system content efficiently - avoid string ops when possible
        system_content = (
            f"{self.SYSTEM_PROMPT}\n\nPrevious conversation:\n{conversation_history}"
            if conversation_history 
            else self.SYSTEM_PROMPT
        )
        
        # Prepare initial messages
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": query}
        ]
        
        # Add tools if available (ModelScope Qwen supports tools)
        api_params = {
            **self.base_params,
            "messages": messages
        }
        
        if tools:
            # Convert tools to OpenAI format
            openai_tools = []
            for tool in tools:
                openai_tool = {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"]
                    }
                }
                openai_tools.append(openai_tool)
            api_params["tools"] = openai_tools
            api_params["tool_choice"] = "auto"
        
        try:
            # Handle sequential tool execution with up to 2 rounds
            if tools and tool_manager:
                return self._handle_sequential_tool_execution(api_params, tool_manager)
            
            # Get direct response if no tools or tool manager
            response = self.client.chat.completions.create(**api_params)
            return response.choices[0].message.content
            
        except Exception as e:
            # Return a more descriptive error message
            return f"Query failed: {str(e)}"
    
    def _handle_sequential_tool_execution(self, initial_params: Dict[str, Any], tool_manager):
        """
        Handle sequential tool execution with up to 2 rounds of tool calls.
        
        Args:
            initial_params: Initial API parameters
            tool_manager: Manager to execute tools
            
        Returns:
            Final response text after all tool execution
        """
        messages = initial_params["messages"].copy()
        tools = initial_params.get("tools", [])
        
        # Keep track of rounds to limit to 2
        round_count = 0
        max_rounds = 2
        
        try:
            while round_count < max_rounds:
                # Prepare API call with current messages and tools
                api_params = {
                    **self.base_params,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto"
                }
                
                # Get response from AI
                response = self.client.chat.completions.create(**api_params)
                choice = response.choices[0]
                
                # Check if we have tool calls
                if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                    # Add AI's response to messages
                    messages.append(choice.message)
                    
                    # Execute all tool calls and collect results
                    tool_results = []
                    for tool_call in choice.message.tool_calls:
                        try:
                            # Execute tool with provided arguments
                            tool_result = tool_manager.execute_tool(
                                tool_call.function.name, 
                                **eval(tool_call.function.arguments)  # Convert string arguments to dict
                            )
                            
                            tool_results.append({
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": tool_call.function.name,
                                "content": tool_result
                            })
                        except Exception as e:
                            # If a tool fails, return error message
                            return f"Tool execution failed: {str(e)}"
                    
                    # Add all tool results to messages
                    messages.extend(tool_results)
                    
                    # Increment round counter
                    round_count += 1
                    
                    # Continue to next round
                    continue
                else:
                    # No more tool calls, return final response
                    return choice.message.content
            
            # If we've reached max rounds, make one final call without tools
            final_params = {
                **self.base_params,
                "messages": messages
            }
            
            final_response = self.client.chat.completions.create(**final_params)
            return final_response.choices[0].message.content
            
        except Exception as e:
            # Return a more descriptive error message
            return f"Sequential tool execution failed: {str(e)}"