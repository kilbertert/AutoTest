// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

import * as vscode from "vscode";
import { GlobalState } from "./globalState";
import { SidebarProvider } from "./sidebar/SidebarProvider";

let sidebar: SidebarProvider | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  GlobalState.initialize(context);

  sidebar = new SidebarProvider(context);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(SidebarProvider.viewType, sidebar),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("trendpower-shell.openSidebar", () =>
      SidebarProvider.openSidebar(),
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("trendpower-shell.runPrompt", () =>
      sidebar?.runPromptFromCommand(),
    ),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("trendpower-shell.cancelRun", () =>
      sidebar?.cancelRun(),
    ),
  );

  // Surface a hint the first time the extension loads.
  const hasShownHint = context.globalState.get<boolean>("trendpower-shell.hintShown");
  if (!hasShownHint) {
    vscode.window.showInformationMessage(
      "Trendpower Shell is active. Open the Trendpower activity-bar icon to run prompts.",
      "Open Sidebar",
    ).then((choice) => {
      if (choice === "Open Sidebar") {
        SidebarProvider.openSidebar();
      }
    });
    context.globalState.update("trendpower-shell.hintShown", true);
  }
}

export function deactivate(): void {
  // No global resources to release; the runner is GC'd with the sidebar.
}