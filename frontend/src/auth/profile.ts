import { useQuery } from "@tanstack/react-query";
import { supabase } from "../lib/supabase";

export interface UserProfile {
  user_id: string;
  default_display_name: string;
  default_color: string;
}

export function useProfile(userId?: string) {
  return useQuery({
    queryKey: ["profile", userId],
    enabled: Boolean(userId),
    queryFn: async (): Promise<UserProfile | null> => {
      const { data, error } = await supabase
        .from("user_profiles")
        .select("user_id, default_display_name, default_color")
        .eq("user_id", userId!)
        .maybeSingle();
      if (error) throw error;
      return data;
    },
  });
}
